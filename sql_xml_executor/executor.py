import os
import re
import logging
from xml.etree import ElementTree as ET
from typing import Dict, Any, List, Optional, Union
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
DEBUG_SQL_LOG=os.environ.get('DEBUG_SQL_LOG', True)

# XML 转义符常量映射表
XML_ENTITY_MAPPING = {
    "&lt;": "<",
    "&gt;": ">",
    "&amp;": "&",
    "&apos;": "'",
    "&quot;": '"',
}

SENSITIVE_KEYS = {"password", "secret", "token", "key"}

class SqlXmlExecutor:
    def __init__(self, db: AsyncSession, mapper_dir: str = "mapper"):
        self.db = db
        self.raw_queries = self.load_queries(mapper_dir)

    def load_queries(self, dir_path: str) -> Dict[str, Dict[str, str]]:
        queries = {}
        for filename in os.listdir(dir_path):
            if filename.endswith('.xml'):
                module = filename.split('.')[0]
                file_path = os.path.join(dir_path, filename)
                tree = ET.parse(file_path)
                root = tree.getroot()
                queries[module] = {}
                for query in root.findall('query'):
                    query_id = query.get('id')
                    queries[module][query_id] = ET.tostring(query, encoding='unicode')
        return queries

    def _decode_xml_entities(self, text: str) -> str:
        for entity, char in XML_ENTITY_MAPPING.items():
            text = text.replace(entity, char)
        return text

    def _safe_log_params(self, params: dict) -> dict:
        return {k: "***" if any(x in k for x in SENSITIVE_KEYS) else v for k, v in params.items()}

    def _replace_placeholders(self, sql: str, replacements: Dict[str, str]) -> str:
        for k, v in replacements.items():
            sql = sql.replace(k, v)
        return sql

    def _get_full_query_text(self, element: ET.Element, params: dict = None) -> str:
        if params is None:
            params = {}
        result = []

        if element.text:
            result.append(element.text)

        for child in element:
            tag = child.tag.lower()

            if tag == "if":
                condition = child.attrib.get("test", "")
                if self._safe_eval_condition(condition, params):
                    result.append(self._get_full_query_text(child, params))

            elif tag == "choose":
                matched = False
                for when in child.findall("when"):
                    cond = when.attrib.get("test", "")
                    if not matched and self._safe_eval_condition(cond, params):
                        result.append(self._get_full_query_text(when, params))
                        matched = True
                if not matched:
                    otherwise = child.find("otherwise")
                    if otherwise is not None:
                        result.append(self._get_full_query_text(otherwise, params))

            elif tag == "where":
                inner = self._get_full_query_text(child, params).strip()
                if inner:
                    inner = re.sub(r'^\s*(AND|OR)\s+', '', inner, flags=re.IGNORECASE)
                    result.append(f" WHERE {inner}")

            else:
                result.append(self._get_full_query_text(child, params))

            if child.tail:
                result.append(child.tail)

        return ''.join(result)

    def _safe_eval_condition(self, condition: str, params: dict) -> bool:
        import ast
        try:
            condition = condition.strip()
            if re.match(r'^\w+$', condition) and condition in params:
                condition = f"{condition} != None"

            expr = self._substitute_variables(condition, params)

            # 安全地解析 AST 表达式
            expr_ast = ast.parse(expr, mode='eval')
            for node in ast.walk(expr_ast):
                if not isinstance(node, (ast.Expression, ast.Name, ast.Load, ast.BinOp,
                                        ast.UnaryOp, ast.BoolOp, ast.Compare,
                                        ast.And, ast.Or, ast.Eq, ast.NotEq,
                                        ast.Lt, ast.LtE, ast.Gt, ast.GtE,
                                        ast.Is, ast.IsNot, ast.Constant, ast.Str, ast.Num)):
                    raise ValueError(f"不安全表达式：{expr}")
            return eval(expr, {"__builtins__": {}}, {})
        except Exception as e:
            logger.warning(f"条件评估失败: {condition} -> {e}")
            return False

    def _substitute_variables(self, expr: str, params: dict) -> str:
        # 避免被部分匹配，先替换长变量名
        for key in sorted(params, key=len, reverse=True):
            value = params[key]
            safe_key = re.escape(key)
            if isinstance(value, str):
                expr = re.sub(rf"\b{safe_key}\b", f"'{value}'", expr)
            elif isinstance(value, (int, float, bool)):
                expr = re.sub(rf"\b{safe_key}\b", str(value).lower(), expr)
            elif value is None:
                expr = re.sub(rf"\b{safe_key}\b", "None", expr)
        return expr

    async def execute(
        self,
        module: str,
        query_id: str,
        params: Optional[Dict[str, Any]] = None,
        single_row: bool = False,
        v_return_obj: bool = True,
        schema: Any = None,
        replace_params: Optional[Dict[str, str]] = None,
    ) -> Union[List[Dict], Dict, None]:
        
        if module not in self.raw_queries or query_id not in self.raw_queries[module]:
            raise ValueError(f"Query ID '{query_id}' not found in module '{module}'")

        raw_query_xml = self.raw_queries[module][query_id]
        query_element = ET.fromstring(raw_query_xml)

        final_sql = self._get_full_query_text(query_element, params or {})
        final_sql = self._decode_xml_entities(final_sql)
        if replace_params:
            final_sql = self._replace_placeholders(final_sql, replace_params)

        if DEBUG_SQL_LOG:
            logger.info(f"[SQL Query] Module: {module}, Query ID: {query_id}")
            logger.info(f"Parsed SQL:\n{final_sql}")
            logger.debug(f"Params: {self._safe_log_params(params or {})}")

        result = await self.db.execute(text(final_sql), params or {})
        rows = result.mappings().all()

        if not rows:
            return None

        data = [dict(row) for row in rows]
        if v_return_obj and schema:
            data = [schema(**item) for item in data]

        return data[0] if single_row else data

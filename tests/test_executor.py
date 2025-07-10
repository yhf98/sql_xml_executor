import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sql_xml_executor.executor import SqlXmlExecutor

DATABASE_URL = "mysql+asyncmy://root:123456@127.0.0.1:3306/test"

engine = create_async_engine(DATABASE_URL, echo=True)

AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

async def main():
    async with AsyncSessionLocal() as db:
        query_executor = SqlXmlExecutor(db)
        user_api_result = await query_executor.execute(
                module="user_stats",
                query_id="getUserDailyGrowth",
                params={
                    "start_time": "2024-01-01 00:00:00",
                    "end_time": "2026-01-01 00:00:00",
                }
            )
        
        print(user_api_result)


if __name__ == "__main__":
    asyncio.run(main())
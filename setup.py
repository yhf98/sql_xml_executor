# setup.py
from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="sql_xml_executor",
    version="0.4.0",
    author="Yao Hengfeng",
    author_email="yaohengfeng98@gmail.com",
    description="A dynamic SQL query executor using XML configuration for SQLAlchemy and FastAPI.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yhf98/sql_xml_executor",
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.7',
    install_requires=[
        "sqlalchemy>=2.0",
        "fastapi>=0.68.0",
        "asyncpg>=0.27.0",
        "python-dotenv>=0.19.0",
    ],
)
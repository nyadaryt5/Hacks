"""Packaging for ULTRON v6.

The implementation lives in the ``ultron`` package; ``ultron_v6`` is kept as
a backwards-compatible entry module and console-script target.
"""

import re
from pathlib import Path

from setuptools import find_packages, setup

HERE = Path(__file__).resolve().parent
LONG_DESCRIPTION = (HERE / "README.md").read_text(encoding="utf-8")
INIT = (HERE / "ultron" / "__init__.py").read_text(encoding="utf-8")
VERSION = re.search(r'__version__ = "([^"]+)"', INIT).group(1)

setup(
    name="ultron-v6",
    version=VERSION,
    description="Production-Grade Autonomous Pentest Framework",
    long_description=LONG_DESCRIPTION,
    long_description_content_type="text/markdown",
    author="nyadaryt5",
    license="MIT",
    python_requires=">=3.10",
    packages=find_packages(include=["ultron", "ultron.*"]),
    py_modules=["ultron_v6"],
    package_data={"ultron": ["py.typed"]},
    install_requires=[
        "pydantic>=2.0.0",
        "pydantic-settings>=2.0.0",
        "sqlalchemy>=2.0.0",
        "httpx>=0.27.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0",
            "pytest-cov>=4.0",
            "flake8>=6.0",
            "mypy>=1.0",
            "ruff>=0.4",
            "bandit>=1.7",
            "pip-audit>=2.6",
            "pip-tools>=7.0",
        ],
        "chroma": ["chromadb>=0.4.0"],
        "all": ["chromadb>=0.4.0"],
    },
    entry_points={
        "console_scripts": [
            "ultron-v6=ultron.cli:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Intended Audience :: Information Technology",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Security",
    ],
)

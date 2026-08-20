from setuptools import setup, find_packages

setup(
    name="ultron-v6",
    version="6.0.0",
    description="Production-Grade Autonomous Pentest Framework",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="nyadaryt5",
    license="MIT",
    python_requires=">=3.10",
    packages=find_packages(),
    py_modules=["ultron_v6"],
    install_requires=[
        "pydantic>=2.0.0",
        "pydantic_settings>=2.0.0",
        "sqlalchemy>=2.0.0",
        "chromadb>=0.4.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0",
            "pytest-cov>=4.0",
            "flake8>=6.0",
            "mypy>=1.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "ultron-v6=ultron_v6:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Information Technology",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Security",
    ],
)
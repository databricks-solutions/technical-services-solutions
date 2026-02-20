from setuptools import setup, find_packages

setup(
    name="migration-accelerator",
    version="0.2.0",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.11",
    entry_points={
        "console_scripts": [
            "migration-accelerator=migration_accelerator.cli:main",
            "ma=migration_accelerator.cli:main",
        ],
    },
)

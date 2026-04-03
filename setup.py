from pathlib import Path

from setuptools import find_packages, setup


README = Path(__file__).with_name("README.md").read_text(encoding="utf-8")


setup(
    name="agent-assisted-lean-formalization-engine",
    version="0.1.0",
    description="Filesystem-first scaffold for an agentic Lean formalization engine.",
    long_description=README,
    long_description_content_type="text/markdown",
    author="Murphy",
    license="MIT",
    package_dir={"": "src"},
    packages=find_packages("src"),
    package_data={
        "lean_formalization_engine": [
            "workspace_template/*",
            "workspace_template/FormalizationEngineWorkspace/*",
        ]
    },
    install_requires=[],
    extras_require={
        "pdf": [
            "PyMuPDF>=1.24",
            "pypdf>=5.0",
        ],
        "dev": [
            "mypy>=1.10",
            "ruff>=0.6",
        ],
    },
    entry_points={
        "console_scripts": [
            "lean-formalize=lean_formalization_engine.cli:main",
        ]
    },
    python_requires=">=3.9",
    include_package_data=True,
)

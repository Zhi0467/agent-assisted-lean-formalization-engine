from setuptools import find_packages, setup


setup(
    name="agent-assisted-lean-formalization-engine",
    version="0.1.0",
    description="Filesystem-first scaffold for an agentic Lean formalization engine.",
    packages=find_packages("src"),
    package_dir={"": "src"},
    python_requires=">=3.9",
    extras_require={
        "pdf": ["PyMuPDF>=1.24", "pypdf>=5.0"],
        "dev": ["mypy>=1.10", "ruff>=0.6"],
    },
    entry_points={
        "console_scripts": [
            "lean-formalize=lean_formalization_engine.cli:main",
        ]
    },
)

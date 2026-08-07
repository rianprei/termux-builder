from setuptools import setup, find_packages

setup(
    name="termux-builder",
    version="3.4.3",
    description="Android Studio no Termux — build APK sem root, sem PC",
    author="rianprei",
    url="https://github.com/rianprei/termux-builder",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=["pyyaml>=6.0", "requests>=2.28.0"],
    entry_points={
        "console_scripts": [
            "termux-builder=builder.cli:main",
        ],
    },
    license="MIT",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: Android",
        "Topic :: Software Development :: Build Tools",
    ],
)

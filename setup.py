from setuptools import setup

import aioevsourcing

_VERSION = "0.0.1"


def readme():
    with open("README.md") as f:
        return f.read()


setup(
    name="aioevsourcing",
    version=_VERSION,
    description="Event sourcing framework for AsyncIO",
    long_description=readme(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Framework :: AsyncIO",
        "Intended Audience :: Developers",
        "License :: Other/Proprietary License",
        "Programming Language :: Python :: 3.7",
        "Topic :: Software Development :: Libraries :: Application Frameworks",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    keywords="asyncio events event sourcing",
    url="http://github.com/dailymotion/aioevsourcing",
    author="Loris Zinsou",
    author_email="loris.zinsou@dailymotion.com",
    license="Proprietary",
    packages=["aioevsourcing"],
    install_requires=["typing_extensions"],
    zip_safe=False,
    setup_requires=["pytest-runner"],
    tests_require=["pytest", "pytest-asyncio", "pytest-cov"],
    extras_require={
        "testing": [
            "asynctest==0.12.2",
            "black==18.6b4",
            "mypy==0.630",
            "pytest==3.7.4",
            "pytest-asyncio==0.9.0",
            "pytest-cov==2.6.0",
            "pytest-runner==4.2",
            "pylint==2.1.1",
            "xenon==0.5.4",
        ]
    },
)

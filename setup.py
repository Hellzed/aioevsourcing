from setuptools import setup

import aioevsourcing


def readme():
    with open("README.md") as f:
        return f.read()


setup(
    name="aioevsourcing",
    version=aioevsourcing.__version__,
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
    tests_require=["pytest", "pytest-asyncio", "pytest-cov", "pytest-mccabe"],
)

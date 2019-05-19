from setuptools import setup, find_packages


with open('README.rst') as f:
    readme = f.read()

with open('LICENSE') as f:
    license = f.read()

setup(
    name='tagtrail',
    version='0.1.0',
    description='A bundle of tools for minimal-cost, self-service community stores.',
    long_description=readme,
    author='Simon Greuter',
    author_email='simon.greuter@gmx.net',
    url='https://github.com/greuters/tagtrail',
    license=license,
    packages=find_packages(exclude=('tests', 'docs'))
)


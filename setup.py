from setuptools import setup, find_packages

setup(
    name='aiosocket',
    version='0.1.0',
    description='Async library for working with socket.socket and ssl.SSLSocket with SOCKS5 support and async HTTP client.',
    author='Vitaliy',
    author_email='your.email@example.com',
    url='https://github.com/vitalya420/aiosocket',
    packages=find_packages('src'),
    package_dir={'': 'src'},
    install_requires=[
        'asyncio',
    ],
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.6',
)

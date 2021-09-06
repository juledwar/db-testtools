import setuptools

setuptools_version = tuple(map(int, setuptools.__version__.split(".", 2)[:2]))
if setuptools_version < (34, 4):
    raise RuntimeError("setuptools 34.4 or newer is required, detected ",
                       setuptools_version)

if __name__ == "__main__":
    setuptools.setup(
        setup_requires=["pbr>=2.0.0"],
        pbr=True)

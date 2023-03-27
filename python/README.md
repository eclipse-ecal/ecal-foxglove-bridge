# Python implementation of eCAL Foxglove Bridge

This folder provides a Python implementation of the eCAL Foxglove bridge.

## Installation instructions

For installation, you will need a recent Python version (>= 3.8).
We recommend to setup the Bridge in an isolated Python environment.
Please download the Python wheel matching to your eCAL installation and OS from the [Github Release Page](https://github.com/eclipse-ecal/ecal/releases).
As eCAL is not yet available as a PyPi package, it cannot be installed automatically via pip.

Then install all requirements plus the eCAL wheel:
```
pip install -r requirements.txt
pip install /path/to/ecal-wheel.whl
```

## Usage

After installing all requirements, the bridge can be launched by running

```
python ./ecal-foxglove-bridge.py
```
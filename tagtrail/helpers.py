#  tagtrail: A bundle of tools to organize a minimal-cost, trust-based and thus
#  time efficient accounting system for small, self-service community stores.
#
#  Copyright (C) 2019, Simon Greuter
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.

from abc import ABC, abstractmethod
import slugify
import shutil

class IdentifiableObject(ABC):
    def __init__(self,
            objId):
        self._id = objId

class Member(IdentifiableObject):
    def __init__(self,
            memberId,
            names,
            emails
            ):
        super().__init__(memberId)
        self._names = names
        self._emails = emails

class Product(IdentifiableObject):
    def __init__(self,
            description,
            unit,
            price,
            quantity
            ):
        super().__init__(slugify.slugify(description))
        self._description = description
        self._unit = unit
        self._price = float(price)
        self._quantity = quantity

def roundPriceCH(price):
    # round to 5-cent precision
    # price : float
    # returns float
    return round(price * 20) / 20

def formatPrice(price):
    # price : float
    # returns string
    price = str(price)
    if "." in price:
        i, d = price.split(".")
    else:
        i = price
        d = ""
    d = d + "00"
    return i + "." + d[0:2]

class Log(ABC):
    LEVEL_DEBUG = 0
    LEVEL_WARN = 1
    LEVEL_INFO = 2
    LEVEL_ERROR = 3

    defaultLogLevel = LEVEL_WARN

    def __init__(self, logLevel = defaultLogLevel):
        self._logLevel = logLevel

    def debug(self, msg, *args, **kwargs):
        if self._logLevel<=Log.LEVEL_DEBUG:
            self._print(msg, *args, **kwargs)

    def warn(self, msg, *args, **kwargs):
        if self._logLevel<=Log.LEVEL_WARN:
            self._print(msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        if self._logLevel<=Log.LEVEL_INFO:
            self._print(msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        if self._logLevel<=Log.LEVEL_ERROR:
            self._print(msg, *args, **kwargs)

    def _print(self, msg, *args, **kwargs):
        if isinstance(msg, str):
            print(msg.format(*args, **kwargs))
        else:
            print(msg)

def recreateDir(path, log = Log()):
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        log.warn('Directory not found: {}', path)
    shutil.os.mkdir(path)



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

class Member(ABC):
    def __init__(self,
            memberId,
            names,
            emails
            ):
        self._id = memberId
        self._names = names
        self._emails = emails

class Product(ABC):
    def __init__(self,
            productId,
            description,
            unit,
            price,
            quantity
            ):
        self._id = productId
        self._description = description
        self._unit = unit
        self._price = price
        self._quantity = quantity

class Log(ABC):
    LEVEL_DEBUG = 0
    LEVEL_WARN = 1
    LEVEL_INFO = 2

    defaultLogLevel = LEVEL_WARN

    def __init__(self, logLevel = defaultLogLevel):
        self._logLevel = logLevel

    def debug(self, msg, *args, **kwargs):
        if self._logLevel<=self.LEVEL_DEBUG:
            self.print(msg, *args, **kwargs)

    def warn(self, msg, *args, **kwargs):
        if self._logLevel<=self.LEVEL_WARN:
            self.print(msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        if self._logLevel<=self.LEVEL_INFO:
            self.print(msg, *args, **kwargs)

    def print(self, msg, *args, **kwargs):
        if isinstance(msg, str):
            print(msg.format(*args, **kwargs))
        else:
            print(msg)



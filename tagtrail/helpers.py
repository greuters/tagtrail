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
import shutil
import os
import datetime
import time
import re

class DateUtility:
    dateFormat = '%Y-%m-%d'

    @classmethod
    def today(cls):
        return datetime.date.today()

    @classmethod
    def todayStr(cls):
        return DateUtility.today().strftime(cls.dateFormat)

    @classmethod
    def strftime(cls, date, dateFormat = None):
        if dateFormat is None:
            dateFormat = cls.dateFormat
        return date.strftime(dateFormat)

    @classmethod
    def strptime(cls, dateStr, dateFormat = None):
        if dateFormat is None:
            dateFormat = cls.dateFormat
        t = time.strptime(dateStr, cls.dateFormat)
        return datetime.date(t.tm_year, t.tm_mon, t.tm_mday)

def readPrefixRow(prefix, row):
    if len(row) < 2:
        raise ValueError(f'len(row) < 2; row = {row}')
    if not all(e is None or e == '' for e in row[2:]):
        raise ValueError(f'row[2:] contains non-null elements, {row}')
    if row[0] != prefix:
        raise ValueError(f"row[0] = '{row[0]}', but expected '{prefix}'")
    return row[1]

def roundPriceCH(price):
    # round to 5-cent precision
    # price : float
    # returns float
    return round(price * 20) / 20

def formatPrice(price, currency = None):
    # price : float
    # returns string
    if currency is None:
        return '%.2f' % (price)
    else:
        return f'%.2f {currency}' % (price)


def priceFromFormatted(priceStr):
    numberOnly = ''.join(re.findall('\d|\.', priceStr))
    if numberOnly:
        return float(numberOnly)
    else:
        return 0

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
        log.debug('Directory not found: {}', path)
    shutil.os.mkdir(path)

# retrieve names of all files directly in directory 'dir' (no recursion)
# return an alphabetically sorted list of them
# optionally filter for extension 'ext'
# if 'removeExt' is true and ext is given, return the name without extension
def sortedFilesInDir(path, ext = None, removeExt = False):
    filteredNames = None
    for (_, _, fileNames) in os.walk(path):
        filteredNames = sorted(
                filter(lambda f:
                    ext == None or os.path.splitext(f)[1] == ext,
                    fileNames))
        if ext and removeExt:
            filteredNames = map(lambda f: os.path.splitext(f)[0], filteredNames)
        break
    if not filteredNames:
        return []
    else:
        return filteredNames

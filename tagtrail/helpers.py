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
from keyrings.cryptfile.cryptfile import CryptFileKeyring
import getpass

class Keyring:
    """
    Convenience wrapper to CryptFileKeyring
    """
    numKeyringOpeningAttempts = 3

    def __init__(self,
            key_file_path,
            keyring_password = None):
        """
        Open keyring from file

        :param key_file_path: path to the credentials file
        :type key_file_path: str
        :param keyring_password: password to open the keyring. if it is None,
            the user will be asked to enter it interactively
        :type  keyring_password: str
        """
        self._key_file_path = key_file_path
        self._keyring_password = keyring_password
        self._keyring = CryptFileKeyring()

    def get_password(self, service, username):
        """
        Retrieve stored password from keyring, opening the keyring first if
        necessary.

        :param service: name of the service to retrieve the password for
        :type service: str
        :param username: username to retrieve the password for
        :type username: str
        :raises ValueError: if the keyring could not be opened (wrong password)
        :raises KeyError: if no password for the given service and username is
            stored in the keyring
        """
        password = None
        for attempt in range(self.numKeyringOpeningAttempts):
            try:
                self._keyring.file_path = self._key_file_path
                if self._keyring_password is not None:
                    self._keyring.keyring_key = self._keyring_password
                # this call asks the user for the keyring password in the
                # background if the keyring is not opened yet
                # if it is wrong, a ValueError is raised - ugly, but this is
                # the only working solution I found so far
                password = self._keyring.get_password(service, username)
                break
            except ValueError:
                print('Failed to open keyring - Wrong password?')
                self._keyring = CryptFileKeyring()
        else:
            raise ValueError('Failed to open keyring - run out of retries')

        if password is None:
            raise KeyError(f'No password stored for service = {service} '
                    f'and username = {username}')
        else:
            return password

    def get_and_ensure_password(self, service, username):
        """
        Retrieve stored password from keyring, opening the keyring first if
        necessary.
        If the password is not available, the user is asked to enter one, which
        is then stored and returned.

        :param service: name of the service to retrieve the password for
        :type service: str
        :param username: username to retrieve the password for
        :type username: str
        :raises ValueError: if the keyring could not be opened (wrong password)
        """
        try:
            return self.get_password(service, username)
        except KeyError:
            password = getpass.getpass(f'Password for {username}:')
            # if we made it here, the keyring is opened - no ValueError
            # expected any more
            self._keyring.set_password(service, username, password)
            return password

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
        try: 
            t = time.strptime(dateStr, dateFormat)
        except ValueError as e:
            print(f'Error: expected format: {dateFormat}')
            raise ValueError(f'Expected format: {dateFormat}') from e
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
    os.makedirs(path)

# retrieve names of all files directly in directory 'dir' (no recursion)
# return an alphabetically sorted list of them
# optionally filter for extension 'ext'
# if 'removeExt' is true and ext is given, return the name without extension
def sortedFilesInDir(path, ext = None, removeExt = False):
    filteredNames = sorted(
            filter(lambda f:
                ext == None or os.path.splitext(f)[1] == ext,
                os.listdir(path)))
    if ext and removeExt:
        filteredNames = map(lambda f: os.path.splitext(f)[0], filteredNames)

    if not filteredNames:
        return []
    else:
        return filteredNames

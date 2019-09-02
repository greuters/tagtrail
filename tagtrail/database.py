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
"""
.. module:: database
   :platform: Linux
   :synopsis: Helper module to read and make input data available.

.. moduleauthor:: Simon Greuter <simon.greuter@gmx.net>


"""


from abc import ABC, abstractmethod
from helpers import Member, Product, Log
from functools import partial
import csv

class Database(ABC):
    """
    Simple in-memory data storage for all entities which
    are relevant during a single accounting run.

    Data is read from simple CSV files with fixed format:
        .. note::
            the following format descriptions use
            ";" as :py::attr:`.csvDelimiter`
            and "," as :py::attr:`.colInternalDelimiter`

        * Expected member format:
            =========  ============  =================
            memberId;  names;        emails
            _________  ____________  _________________
            MIR     ;  Name1,Name2;  mail1, mail2, ...
            =========  ============  =================

        * Expected product format:
            ===================  =====  =========
            description;         unit;  price
            ___________________  _____  _________
            Organic brown rice;  500g;  123 CHF
            ===================  =====  =========

    """
    csvDelimiter = ';'
    "Delimiter between csv columns. default value: ';'"
    colInternalDelimiter = ','
    quotechar = '"'
    newline = ''

    def __init__(self,
            memberFilePath,
            productFilePath):
        self._log = Log()
        self._members = self.readRowsFromCSV(memberFilePath,
                partial(self.memberFromRow),
                1)
        self._products = self.readRowsFromCSV(productFilePath,
                partial(self.productFromRow),
                1)

    def memberFromRow(self, row):
        return Member(row[0], row[1], row[2])

    def productFromRow(self, row):
        return Product(row[0], row[1], row[2], int(row[3]))

    def readRowsFromCSV(self, path, rowProcessor, skipCnt=0):
        d = {}
        with open(path, newline=self.newline) as csvfile:
            reader = csv.reader(csvfile, delimiter=self.csvDelimiter,
                    quotechar=self.quotechar)
            for cnt, row in enumerate(reader):
                if cnt<skipCnt:
                    continue
                self._log.debug("row={}", row)
                idObj = rowProcessor(row)
                d[idObj._id]= idObj
        return d

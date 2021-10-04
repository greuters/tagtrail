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
from functools import partial
import csv
import datetime
import slugify
import copy
import re
import itertools
import configparser
from collections import UserDict, UserList

from . import helpers

class Database(ABC):
    """
    Simple in-memory data storage for all entities which
    are relevant during a single accounting run.
    """

    log = helpers.Log()

    def __init__(self,
            dataPath,
            memberFileName = 'members',
            productFileName = 'products',
            configFilePath = 'config/tagtrail.cfg'):
        self.memberFilePath = dataPath + memberFileName + '.tsv'
        self.productFilePath = dataPath + productFileName + '.csv'
        self.config = configparser.ConfigParser(
                interpolation=configparser.ExtendedInterpolation(),
                converters={
                    'csvlist': lambda x: [i.strip() for i in x.split(',') if
                        i.strip() != ''],
                    'newlinelist': lambda x: [i.strip() for i in x.splitlines()
                        if i.strip() != '']})
        self.log.info(f'Reading configuration from {configFilePath}')
        self.configFilePath = configFilePath
        self.config.read(configFilePath)
        self.log.info(f'Reading members from {self.memberFilePath}')
        self.members = self.readCsv(self.memberFilePath, MemberDict)
        self.log.info(f'Reading products from {self.productFilePath}')
        self.products = self.readCsv(self.productFilePath, ProductDict)

    def writeConfig(self):
        with open(self.configFilePath, 'w') as configFile:
            self.config.write(configFile)

    def readCsv(self, path, containerClass):
        """
        containerClass must be DatabaseDict or DatabaseList
        """
        def addDbObjectToDict(dbObject, container):
            if dbObject.id in container:
                raise ValueError(f'duplicate key {dbObject.id} in {path}')
            container[dbObject.id] = dbObject

        def addDbObjectToList(dbObject, container):
            container.append(dbObject)

        self.log.debug(f'reading csv file {path}')
        with open(path, newline=containerClass.newline, encoding=containerClass.encoding) as csvfile:
            reader = csv.reader(csvfile, delimiter=containerClass.csvDelimiter,
                    quotechar=containerClass.quotechar)
            prefixRows = self.config.getnewlinelist(
                    containerClass.configSection(),
                    containerClass.prefixRowsConfigOption())
            columnHeaders = self.config.getnewlinelist(
                    containerClass.configSection(),
                    containerClass.columnHeadersConfigOption())
            prefixValues = []

            for cnt, row in enumerate(reader):
                self.log.debug("row={}", row)
                if cnt<len(prefixRows):
                    prefixValues.append(
                            helpers.readPrefixRow(prefixRows[cnt], row))

                elif cnt==len(prefixRows):
                    for expectedHeader, actualHeader in itertools.zip_longest(columnHeaders, row):
                        if expectedHeader != actualHeader:
                            raise ValueError(
                            f"expectedHeader '{expectedHeader}' != actualHeader '{actualHeader}'")

                    if issubclass(containerClass, DatabaseDict):
                        container = containerClass(self.config, *prefixValues)
                        addDbObject = addDbObjectToDict
                    elif issubclass(containerClass, DatabaseList):
                        container = containerClass(self.config, *prefixValues)
                        addDbObject = addDbObjectToList
                    else:
                        raise TypeError('containerClass must be a DatabaseDict or DatabaseList')

                else:
                    vals = []
                    for val in row:
                        if containerClass.colInternalDelimiter is None or \
                        val.find(containerClass.colInternalDelimiter) == -1:
                            vals.append(val)
                        else:
                            vals.append([v.strip() for v in val.split(containerClass.colInternalDelimiter)])
                    self.log.debug(f'vals={vals}')
                    dbObject = container.databaseObjectFromCsvRow(vals)
                    if not dbObject:
                        continue
                    addDbObject(dbObject, container)

            return container

    def writeCsv(self, path, container):
        """
        container must be a DatabaseDict or DatabaseList
        """
        prefixRows = self.config.getnewlinelist(
                container.configSection(),
                container.prefixRowsConfigOption())
        columnHeaders = self.config.getnewlinelist(
                container.configSection(),
                container.columnHeadersConfigOption())
        self.log.debug(f'prefixRows={prefixRows}, prefixValues={container.prefixValues()}')
        assert(len(prefixRows) == len(container.prefixValues()))

        with open(path, "w+", newline=container.newline, encoding=container.encoding) as fout:
            for prefix, val in zip(prefixRows,
                    container.prefixValues()):
                fout.write(f'{prefix}{container.csvDelimiter}{val}\n')

            fout.write(container.csvDelimiter.join(columnHeaders)+"\n")
            for row in container.csvRows():
                assert(len(row) == len(columnHeaders))
                fout.write(container.csvDelimiter.join(row)+"\n")

class DatabaseObject(ABC):
    def __init__(self,
            objId):
        if not isinstance(objId, str):
            raise TypeError('objId must be a string')
        self.id = objId

class DatabaseDict(UserDict):
    """
    Base class for dicts Database can handle.
    """
    csvDelimiter = ';'
    colInternalDelimiter = ','
    quotechar = '"'
    newline = ''
    encoding = 'utf-8'

    def __init__(self, config, **kwargs):
        super().__init__(**kwargs)

    @classmethod
    def configSection(cls):
        raise NotImplementedError

    @classmethod
    def prefixRowsConfigOption(cls):
        return 'prefix_rows'

    @classmethod
    def columnHeadersConfigOption(cls):
        return 'column_headers'

    @classmethod
    def containedDatabaseObjectCls(cls):
        raise NotImplementedError

    def databaseObjectFromCsvRow(self, rowValues):
        raise NotImplementedError

    def prefixValues(self):
        raise NotImplementedError

    def csvRows(self):
        raise NotImplementedError

    def __setitem__(self, key, value):
        if not isinstance(value, DatabaseObject):
            raise TypeError('This dict can only hold values of type ' + \
                    f'{DatabaseObject}. {value} is not.')
        if not isinstance(value, self.containedDatabaseObjectCls()):
            raise TypeError('This dict can only hold values of type ' + \
                    f'{self.containedDatabaseObjectCls()}. {value} is not.')
        if value.id != key:
            raise ValueError(f'Not allowed to store DatabaseObject with ' + \
                    f'a different key than its id, but {key} != {value.id}.')
        super().__setitem__(key, value)

class DatabaseList(UserList):
    """
    Base class for lists Database can handle.
    """
    csvDelimiter = ';'
    colInternalDelimiter = ','
    quotechar = '"'
    newline = ''
    encoding = 'utf-8'

    def __init__(self, config, *args):
        super().__init__(*args)

    @classmethod
    def configSection(cls):
        raise NotImplementedError

    @classmethod
    def prefixRowsConfigOption(cls):
        return 'prefix_rows'

    @classmethod
    def columnHeadersConfigOption(cls):
        return 'column_headers'

    def databaseObjectFromCsvRow(self, rowValues):
        raise NotImplementedError

    def prefixValues(self):
        raise NotImplementedError

    def csvRows(self):
        raise NotImplementedError

class Member(DatabaseObject):
    def __init__(self,
            memberId,
            name,
            emails,
            balance
            ):
        if not type(name) is str:
            raise TypeError(f'name is not a string: {name}')
        if not type(emails) is list:
            raise TypeError(f'emails is not a list: {emails}')
        super().__init__(memberId)
        self.name = name
        self.emails = emails
        self.balance = balance

    @property
    def balance(self):
        return self.__balance

    @balance.setter
    def balance(self, balance):
        if not type(balance) is float:
            raise TypeError(f'balance is not a float: {balance}')
        self.__balance = balance


class MemberDict(DatabaseDict):
    csvDelimiter = '\t'
    def __init__(self,
            config,
            accountingDate,
            **kwargs
            ):
        super().__init__(config, **kwargs)
        self.accountingDate = accountingDate \
                if isinstance(accountingDate, datetime.date) else \
                helpers.DateUtility.strptime(accountingDate)
        header = config.getnewlinelist(self.configSection(),
                self.columnHeadersConfigOption())
        self.numAdditionalCols = len(header) - 4

    @classmethod
    def configSection(cls):
        return 'members'

    @classmethod
    def containedDatabaseObjectCls(cls):
        return Member

    def databaseObjectFromCsvRow(self, rowValues):
        memberId = rowValues[0]
        name = rowValues[1] if isinstance(rowValues[1], str) else ", ".join(rowValues[1])
        if isinstance(rowValues[2], list):
            emails = rowValues[2]
        elif rowValues[2] != '':
            emails = [rowValues[2]]
        else:
            emails = []
        balance = rowValues[3] if rowValues[3] else 0
        return Member(memberId, name, emails, float(balance))

    def prefixValues(self):
        return [self.accountingDate]

    def csvRows(self):
        return [[
            m.id,
            m.name,
            ', '.join(m.emails),
            helpers.formatPrice(m.balance)
            ]+['' for i in range(self.numAdditionalCols)]
            for m in self.values()]

class Product(DatabaseObject):
    def __init__(self,
            description,
            amount,
            unit,
            purchasePrice,
            marginPercentage,
            previousQuantity,
            inventoryQuantity = None,
            addedQuantity = None,
            soldQuantity = None,
            sheetsToPrint = None,
            eaternityName = None,
            origin = None,
            production = None,
            transport = None,
            conservation = None,
            gCo2e = None
            ):
        if not type(description) is str:
            raise TypeError(f'description is not a string, {description}')
        if not type(amount) is int:
            raise TypeError(f'amount is not an integer, {amount}')
        if not type(unit) is str:
            raise TypeError(f'unit is not a string, {unit}')
        if not type(purchasePrice) is float:
            raise TypeError(f'purchasePrice is not a float, {purchasePrice}')
        if not type(marginPercentage) is float:
            raise TypeError(f'marginPercentage is not a float, {marginPercentage}')
        if inventoryQuantity and not type(inventoryQuantity) is int:
            raise TypeError(f'inventoryQuantity is not an integer, {inventoryQuantity}')
        if sheetsToPrint:
            if type(sheetsToPrint) is str:
                sheetsToPrint = [sheetsToPrint]
            if not type(sheetsToPrint) is list:
                raise TypeError(f'sheetsToPrint is not a list, {sheetsToPrint}')
        if eaternityName and not type(eaternityName) is str:
            raise TypeError(f'eaternityName is not a string, {eaternityName}')
        if origin and not type(origin) is str:
            raise TypeError(f'origin is not a string, {origin}')
        if production:
            if type(production) is str:
                production = [production]
            if not type(production) is list:
                raise TypeError(f'production is not a list, {production}')
        if transport:
            if not type(transport) is str:
                raise TypeError(f'transport is not a string, {transport}')
        if conservation:
            if type(conservation) is str:
                conservation = [conservation]
            if not type(conservation) is list:
                raise TypeError(f'conservation is not a list, "{conservation}"')

        super().__init__(slugify.slugify(description))
        self.description = description
        self.amount = amount
        self.unit = unit
        self.purchasePrice = purchasePrice
        self.marginPercentage = marginPercentage
        self.previousQuantity = previousQuantity
        self.inventoryQuantity = inventoryQuantity
        self.addedQuantity = addedQuantity
        self.soldQuantity = soldQuantity
        self.sheetsToPrint = sheetsToPrint
        self.eaternityName = eaternityName
        self.origin = origin
        self.production = production
        self.transport = transport
        self.conservation = conservation
        self.gCo2e = gCo2e

    @property
    def amountAndUnit(self):
        return str(self.amount)+self.unit

    @property
    def addedQuantity(self):
        return self.__addedQuantity

    @addedQuantity.setter
    def addedQuantity(self, addedQuantity):
        if addedQuantity and not type(addedQuantity) is int:
            raise TypeError(f'addedQuantity is not an integer, {addedQuantity}')
        self.__addedQuantity = addedQuantity

    @property
    def soldQuantity(self):
        return self.__soldQuantity

    @soldQuantity.setter
    def soldQuantity(self, soldQuantity):
        if soldQuantity and not type(soldQuantity) is int:
            raise TypeError(f'soldQuantity is not an integer, {soldQuantity}')
        self.__soldQuantity = soldQuantity

    @property
    def previousQuantity(self):
        return self.__previousQuantity

    @previousQuantity.setter
    def previousQuantity(self, previousQuantity):
        if previousQuantity and not type(previousQuantity) is int:
            raise TypeError(f'previousQuantity is not an integer, {previousQuantity}')
        self.__previousQuantity = previousQuantity

    @property
    def expectedQuantity(self):
        if self.__previousQuantity is None \
           or self.__addedQuantity is None \
           or self.__soldQuantity is None:
           return None
        return self.previousQuantity+self.addedQuantity-self.soldQuantity

    def grossSalesPrice(self):
        return helpers.roundPriceCH(self.purchasePrice * (1 + self.marginPercentage))

class ProductDict(DatabaseDict):
    log = helpers.Log()
    def __init__(self,
            config,
            previousQuantityDate,
            expectedQuantityDate,
            inventoryQuantityDate,
            **kwargs
            ):
        super().__init__(config, **kwargs)
        if not isinstance(previousQuantityDate, str):
            raise TypeError(f'previousQuantityDate is not a string: {previousQuantityDate}')
        if not isinstance(expectedQuantityDate, str):
            raise TypeError(f'expectedQuantityDate is not a string: {expectedQuantityDate}')
        if not isinstance(inventoryQuantityDate, str):
            raise TypeError(f'inventoryQuantityDate is not a string: {inventoryQuantityDate}')

        self.previousQuantityDate = None if previousQuantityDate == '' else helpers.DateUtility.strptime(previousQuantityDate)
        self.expectedQuantityDate = None if expectedQuantityDate == '' else helpers.DateUtility.strptime(expectedQuantityDate)
        self.inventoryQuantityDate = None if inventoryQuantityDate == '' else helpers.DateUtility.strptime(inventoryQuantityDate)
        self.productMarginPercentage = config.getfloat('general',
                'product_margin_percentage')

    @classmethod
    def configSection(cls):
        return 'products'

    @classmethod
    def containedDatabaseObjectCls(cls):
        return Product

    def databaseObjectFromCsvRow(self, rowValues):
        if self.inventoryQuantityDate is None:
            if rowValues[8]:
                raise ValueError('Invalid products file: '
                        'inventoryQuantityDate is empty, but '
                        f'inventoryQuantity of {rowValues[0]} is given')
        else:
            if not rowValues[8]:
                raise ValueError('Invalid products file: '
                        f'inventoryQuantityDate {self.inventoryQuantityDate} '
                        f'is given, but inventoryQuantity of {rowValues[0]} '
                        'is missing')

        return Product(description = rowValues[0],
                amount = int(rowValues[1]),
                unit = rowValues[2],
                purchasePrice = float(rowValues[3]),
                marginPercentage = self.productMarginPercentage,
                previousQuantity = int(rowValues[4]),
                addedQuantity = 0 if not rowValues[5] else int(rowValues[5]),
                soldQuantity  = 0 if not rowValues[6] else int(rowValues[6]),
                # not reading expectedQuantity
                inventoryQuantity = None if not rowValues[8] else int(rowValues[8]),
                sheetsToPrint = rowValues[9],
                # Comment is not used within tagtrail
                eaternityName = rowValues[11],
                origin = rowValues[12],
                production = rowValues[13],
                transport = rowValues[14],
                conservation = rowValues[15],
                gCo2e = None if not rowValues[16] else int(rowValues[16]))

    def prefixValues(self):
        return ['' if self.previousQuantityDate is None else str(self.previousQuantityDate),
                '' if self.expectedQuantityDate is None else str(self.expectedQuantityDate),
                '' if self.inventoryQuantityDate is None else str(self.inventoryQuantityDate)]

    def csvRows(self):
        return [[p.description,
                str(p.amount),
                p.unit,
                str(p.purchasePrice),
                '' if p.previousQuantity is None else str(p.previousQuantity),
                '' if p.addedQuantity is None else str(p.addedQuantity),
                '' if p.soldQuantity is None else str(p.soldQuantity),
                '' if p.expectedQuantity is None else str(p.expectedQuantity),
                '' if p.inventoryQuantity is None else str(p.inventoryQuantity),
                '' if p.sheetsToPrint is None else ','.join(p.sheetsToPrint),
                '', # Comment is not used within tagtrail
                '' if p.eaternityName is None else p.eaternityName,
                '' if p.origin is None else p.origin,
                '' if p.production is None else ','.join(p.production),
                '' if p.transport is None else p.transport,
                '' if p.conservation is None else ','.join(p.conservation),
                '' if p.gCo2e is None else str(p.gCo2e)]
                for p in self.values()]

    def copyForNext(self, currentDate, clearAddedQuantity, clearSoldQuantity):
        """
        Copy all products and initialize their quantities

        The copy will be ready to export as an initial template  for the next
        call to tagtrail_account / tagtrail_gen.

        The new previousQuantity is either initialized from self.inventoryQuantity
        (if given) or from self.previousQuantity.

        :param currentDate: date of the current accounting
        :type currentDate: str
        :param clearAddedQuantity: if True, reset addedQuantity to None and add
            it to the new previousQuantity
        :type clearAddedQuantity: bool
        :param clearSoldQuantity: if True, reset soldQuantity to None and
            subtract it from the new previousQuantity
        :type clearSoldQuantity: bool
        """
        assert(self.inventoryQuantityDate is None or self.inventoryQuantityDate == currentDate)

        newProducts = copy.deepcopy(self)
        newProducts.previousQuantityDate = currentDate
        newProducts.expectedQuantityDate = None
        newProducts.inventoryQuantityDate = None

        for productId, product in self.items():
            if product.inventoryQuantity is None:
                newProducts[productId].previousQuantity = product.previousQuantity
                if clearAddedQuantity:
                    newProducts[productId].previousQuantity += product.addedQuantity
                    newProducts[productId].addedQuantity = None
                if clearSoldQuantity:
                    newProducts[productId].previousQuantity -= product.soldQuantity
                    newProducts[productId].soldQuantity = None
            else:
                # inventoryQuantity is the quantity of a product physically in
                # the store after accounting is done.
                # thus
                # * the products added since last tagtrail_gen are counted in
                #   inventoryQuantity
                #   => if we want to transfer addedQuantity to the next products.csv,
                #   it needs to be deducted again from inventoryQuantity
                #
                # * the products sold since last run of tagtrail_account
                #   (soldQuantity) are already gone and not counted in
                #   inventoryQuantity
                #   => if we want to transfer soldQuantity to the next products.csv,
                #   it needs to be added again to inventoryQuantity
                newProducts[productId].previousQuantity = product.inventoryQuantity
                if clearAddedQuantity:
                    newProducts[productId].addedQuantity = None
                else:
                    newProducts[productId].previousQuantity -= product.addedQuantity
                if clearSoldQuantity:
                    newProducts[productId].soldQuantity = None
                else:
                    newProducts[productId].previousQuantity += product.soldQuantity
            assert(newProducts[productId].previousQuantity is not None)
            newProducts[productId].inventoryQuantity = None
            newProducts[productId].sheetsToPrint = None # TODO remove

        return newProducts

class BillPosition(DatabaseObject):
    def __init__(self,
            productId,
            description,
            numTags,
            unitPurchasePrice,
            unitGrossSalesPrice,
            gCo2e):
        super().__init__(productId)
        self.description = description
        self.numTags = numTags
        self.unitPurchasePrice = unitPurchasePrice
        self.unitGrossSalesPrice = unitGrossSalesPrice
        self.gCo2e = gCo2e

    def totalPurchasePrice(self):
        return self.numTags * self.unitPurchasePrice

    def totalGrossSalesPrice(self):
        return self.numTags * self.unitGrossSalesPrice

    def totalGCo2e(self):
        return None if self.gCo2e == None else self.numTags * self.gCo2e

class Bill(DatabaseDict):
    def __init__(self,
            config,
            memberId,
            previousAccountingDate,
            currentAccountingDate,
            previousBalance,
            totalPayments,
            correctionTransaction,
            correctionJustification,
            expectedTotalPrice = None,
            currentExpectedBalance = None,
            expectedTotalGCo2e = None,
            **kwargs
            ):
        super().__init__(config, **kwargs)
        self.memberId = memberId
        self.previousAccountingDate = previousAccountingDate \
                if isinstance(previousAccountingDate, datetime.date) else \
                helpers.DateUtility.strptime(previousAccountingDate)
        self.currentAccountingDate = currentAccountingDate \
                if isinstance(currentAccountingDate, datetime.date) else \
                helpers.DateUtility.strptime(currentAccountingDate)
        self.previousBalance = float(previousBalance)
        self.totalPayments = float(totalPayments)
        self.setCorrection(float(correctionTransaction), correctionJustification)
        self.expectedTotalPrice = expectedTotalPrice
        self.currentExpectedBalance = currentExpectedBalance
        self.expectedTotalGCo2e = expectedTotalGCo2e
        self.textRepresentationHeader = config.get(
                self.configSection(), 'text_representation_header')
        self.textRepresentationRow = config.get(
                self.configSection(), 'text_representation_row')
        self.textRepresentationFooter = config.get(
                self.configSection(), 'text_representation_footer')

    # TODO: remove property and replace with an actual CorrectionTransaction
    @property
    def correctionTransaction(self):
        """
        Tagtrail assumes it has complete knowledge of the new member balance by
        adding up the previous balance, incoming payments and priced tags.

        This is not completely true, as e.g. products might have gone bad and
        are refunded, somebody paid you in cache or you want to change the
        GnuCash file for some other valid reason.

        To make these modifications transparent to the customer, the accountant
        has to justify them and they appear as a summarized correction on the
        bill before being imported to GnuCash.
        """
        return self.__correctionTransaction

    @property
    def correctionJustification(self):
        return self.__correctionJustification

    def setCorrection(self, transaction, justification):
        if (transaction != 0) and (justification == ''):
            raise ValueError('if a correction transaction is made, ' + \
                    'a justification has to be given. ' + \
                    f'transaction={transaction}, justification={justification}')
        self.__correctionTransaction = transaction
        self.__correctionJustification = justification

    def totalGCo2e(self):
        totalGCo2e = sum([0 if p.totalGCo2e() == None else p.totalGCo2e() for p in self.values()])
        if (self.expectedTotalGCo2e and int(totalGCo2e) !=
                int(self.expectedTotalGCo2e)):
            raise ValueError(f'expectedTotalGCo2e ({self.expectedTotalGCo2e}) is '
                    + f'not consistent with sum of gCo2e ({totalGCo2e})')
        return totalGCo2e

    def totalGrossSalesPrice(self):
        totalGrossSalesPrice = sum([p.totalGrossSalesPrice() for p in self.values()])
        if (self.expectedTotalPrice and
                helpers.formatPrice(totalGrossSalesPrice) !=
                self.expectedTotalPrice):
            raise ValueError(f'expectedTotalPrice ({self.expectedTotalPrice}) is '
                    + f'not consistent with sum of prices ({totalGrossSalesPrice})')
        return totalGrossSalesPrice

    def totalPurchasePrice(self):
        return sum([p.totalPurchasePrice() for p in self.values()])

    @property
    def currentBalance(self):
        currentBalance = self.previousBalance + self.totalPayments + \
                self.correctionTransaction - self.totalGrossSalesPrice()
        if (self.currentExpectedBalance and
                helpers.formatPrice(currentBalance) !=
                self.currentExpectedBalance):
            raise ValueError(f'inconsistent price calculation for {memberId},\n'
                    + f'({currentBalance} == {self.previousBalance} + '
                    + f'{self.totalPayments} + {self.correctionTransaction} - '
                    + f'{self.totalGrossSalesPrice()}) != {self.currentExpectedBalance}')
        return currentBalance

    @classmethod
    def configSection(cls):
        return 'bills'

    @classmethod
    def containedDatabaseObjectCls(cls):
        return BillPosition

    def databaseObjectFromCsvRow(self, rowValues):
        numTags = int(rowValues[2])
        unitGrossSalesPrice = helpers.priceFromFormatted(rowValues[3])
        unitGCo2e = None if rowValues[4] == 'None' else int(rowValues[4])
        totalGrossSalesPrice = rowValues[5]
        totalGCo2e = None if rowValues[6] == 'None' else int(rowValues[6])
        position = BillPosition(rowValues[0],
                rowValues[1],
                numTags,
                None,
                unitGrossSalesPrice,
                unitGCo2e)
        if helpers.formatPrice(position.totalGrossSalesPrice()) != totalGrossSalesPrice:
            raise ValueError('inconsistent position, ' + \
                    f'({position.totalGrossSalesPrice()} == {numTags} * {unitGrossSalesPrice}) != {totalGrossSalesPrice}')
        if position.totalGCo2e() != totalGCo2e:
            raise ValueError('inconsistent position, ' + \
                    f'({position.totalGCo2e()} == {numTags} * {unitGCo2e}) != {totalGCo2e}')
        return position

    def prefixValues(self):
        return [self.memberId,
                self.previousAccountingDate,
                self.currentAccountingDate,
                helpers.formatPrice(self.previousBalance),
                helpers.formatPrice(self.totalPayments),
                helpers.formatPrice(self.correctionTransaction),
                self.correctionJustification,
                helpers.formatPrice(self.totalGrossSalesPrice()),
                helpers.formatPrice(self.currentBalance),
                self.totalGCo2e()]

    def csvRows(self):
        return [[p.id,
            p.description,
            str(p.numTags),
            helpers.formatPrice(p.unitGrossSalesPrice),
            'None' if p.gCo2e is None else str(p.gCo2e),
            'None' if p.totalGrossSalesPrice() is None else helpers.formatPrice(p.totalGrossSalesPrice()),
            'None' if p.totalGCo2e() is None else str(p.totalGCo2e())]
                for p in self.values()]

    def __str__(self):
        text = self.textRepresentationHeader + '\n'
        for p in self.values():
            text += (self.textRepresentationRow + '\n').format(
                    description=p.description,
                    numTags=p.numTags,
                    unitPrice=helpers.formatPrice(p.unitGrossSalesPrice),
                    totalPrice=helpers.formatPrice(p.totalGrossSalesPrice()),
                    totalGCo2e='?' if p.totalGCo2e() is None else p.totalGCo2e()
                    )
        text += '\n' + self.textRepresentationFooter.format(
                totalPrice=helpers.formatPrice(self.totalGrossSalesPrice()),
                totalGCo2e=self.totalGCo2e())
        return text

class MemberAccount(DatabaseObject):
    def __init__(self,
            memberId):
        super().__init__(memberId)

class MemberAccountDict(DatabaseDict):
    """
    Configured for import to GnuCash
    """
    def __init__(self,
            config,
            **kwargs):
        super().__init__(config, **kwargs)
        self.prefix = config.get(self.configSection(), 'account_prefix')
        self.type = config.get(self.configSection(), 'type')
        self.commoditym = config.get('general', 'currency')
        self.commodityn = config.get(self.configSection(), 'commodityn')
        self.hidden = config.get(self.configSection(), 'hidden')
        self.tax = config.get(self.configSection(), 'tax')
        self.placeHolder = config.get(self.configSection(), 'place_holder')

    @classmethod
    def configSection(cls):
        return 'member_accounts'

    @classmethod
    def containedDatabaseObjectCls(cls):
        return MemberAccount

    databaseObjectFromCsvRow = None # write-only CSV

    def prefixValues(self):
        return []

    def csvRows(self):
        return [[self.type, self.prefix+a.id, a.id,
                '', '', '', '', self.commoditym, self.commodityn, self.hidden,
                self.tax, self.placeHolder]
                for a in self.values()]

class GnucashTransaction:
    def __init__(self,
            description,
            amount,
            sourceAccount,
            targetAccount,
            date
            ):
        self.description = description
        self.amount = amount
        self.sourceAccount = sourceAccount
        self.targetAccount = targetAccount
        self.date = date

class GnucashTransactionList(DatabaseList):
    """
    Configured for import to GnuCash
    """
    colInternalDelimiter=None

    @classmethod
    def configSection(cls):
        return 'gnucash_transactions'

    def databaseObjectFromCsvRow(self, rowValues):
        return GnucashTransaction(
                date = helpers.DateUtility.strptime(rowValues[0]),
                description = rowValues[1],
                sourceAccount = rowValues[2],
                amount = float(rowValues[3]),
                targetAccount = rowValues[4])

    def prefixValues(self):
        return []

    def csvRows(self):
        return [[helpers.DateUtility.strftime(t.date), t.description, t.sourceAccount,
                helpers.formatPrice(t.amount), t.targetAccount]
                for t in self]

class CorrectionTransaction(DatabaseObject):
    """
    A correction transaction is used to let the member know that some
    correction was done in GnuCash, affecting his balance.

    The corrected amount is not exported to GnuCash again, but meant to make a
    manual correction already done in GnuCash transparent to the user.

    As an example, if member LILA complained about a package of curry gone bad,
    the accountant can refund the price within GnuCash and let LILA know their
    corrected balance and the reason for it during next accounting by adding

    LILA;2.3;Refunded curry

    to 0_input/correctionTransactions.csv
    """
    def __init__(self,
            memberId,
            amount,
            justification):
        super().__init__(memberId)
        self.amount = amount
        self.justification = justification

class CorrectionTransactionDict(DatabaseDict):
    """
    As simple as possible, to allow the user to store correction transactions.
    """
    @classmethod
    def configSection(cls):
        return 'correction_transactions'

    @classmethod
    def prefixRows(cls):
        return 'prefix_rows'

    @classmethod
    def columnHeaders(cls):
        return 'column_headers'

    @classmethod
    def containedDatabaseObjectCls(cls):
        return CorrectionTransaction

    def databaseObjectFromCsvRow(self, rowValues):
        return CorrectionTransaction(
                memberId = rowValues[0],
                amount = float(rowValues[1]),
                justification = rowValues[2])

    def prefixValues(self):
        return []

    def csvRows(self):
        return [[t.id, helpers.formatPrice(t.amount), t.justification]
                for t in self.values()]

class PostfinanceTransaction:
    messagePrefix = 'MITTEILUNGEN:'
    def __init__(self,
            bookingDate,
            notificationText,
            creditAmount,
            debitAmount,
            value,
            balance
            ):
        if (creditAmount is None) == (debitAmount is None):
            raise ValueError('one and only one of ' + \
                    f"creditAmount='{creditAmount}' and " + \
                    f"debitAmount='{debitAmount}'" + \
                    "must be given")
        if not isinstance(bookingDate, datetime.date):
            raise TypeError('bookingDate must be a datetime.date')
        self.bookingDate = bookingDate
        self.notificationText = notificationText
        self.creditAmount = creditAmount
        self.debitAmount = debitAmount
        self.value = value
        self.balance = balance
        self.memberId = None

    def inferMemberId(self, possibleIds):
        """
        Try to receive memberId from notificationText, best effort recall but
        precise.

        We assume the notificationText consists of
        '.*' + self.messagePrefix + '\s*' + 'memberId' + ['\s+' + '.*']*

        If no memberId can be retrieved, or the memberId is not in possibleIds,
        None is returned. If a memberId is returned, you can assume it is the
        correct one.
        """
        match = re.split(self.messagePrefix+'\s*', self.notificationText)
        if match is None or len(match) != 2:
            return None
        else:
            messageAndBehind = match[1]
            messageMatch = re.split('\s', messageAndBehind)
            if messageMatch is None or not messageMatch[0] in possibleIds:
                return None
            else:
                return messageMatch[0]

    def mostLikelyMemberId(self, possibleIds):
        """
        Select the most likely memberId among possibleIds.

        If no single most likely candidate is found, None is returned.
        """
        mostLikelyMemberId = None
        for memberId in possibleIds:
            if self.notificationText.upper().find(f' {memberId.upper()} ') != -1:
                if mostLikelyMemberId is None:
                    mostLikelyMemberId = memberId
                else:
                    return None
        return mostLikelyMemberId

class PostfinanceTransactionList(DatabaseList):
    colInternalDelimiter=None
    encoding = 'latin-1'
    """
    Configured to read standard transaction export from PostFinance
    TODO: hint for programmers, this class needs to be adapted/replaced to
    import payments from different bank
    """
    def __init__(self,
            config,
            dateFrom,
            dateTo,
            entryType,
            account,
            currency,
            *args
            ):
        self.expectedEntryType = config.get(self.configSection(),
                'expected_entry_type')
        self.expectedCurrency = config.get('general', 'currency')
        self.expectedAccount = config.get('general', 'our_iban')
        self.dateFormat = config.get(self.configSection(), 'date_format')
        if entryType != self.expectedEntryType:
            raise ValueError('unexpected entry type ' + \
                    f"'{entryType}', should be '{self.expectedEntryType}'")
        if account != self.expectedAccount:
            raise ValueError('unexpected account ' + \
                    f"'{account}', should be '{self.expectedAccount}'")
        if currency != self.expectedCurrency:
            raise ValueError('unexpected currency ' + \
                    f"'{currency}', should be '{self.expectedCurrency}'")
        super().__init__(config, *args)
        self.dateFrom = helpers.DateUtility.strptime(dateFrom, self.dateFormat)
        self.dateTo = helpers.DateUtility.strptime(dateTo, self.dateFormat)

    @classmethod
    def configSection(cls):
        return 'postfinance_transactions'

    def databaseObjectFromCsvRow(self, rowValues):
        if rowValues in [
                [],
                ['Disclaimer:'],
                ['Disclaimer:', '', '', '', '', ''],
                ['This is not a document created by PostFinance Ltd. PostFinance Ltd is not responsible for the content.'],
                ['This is not a document created by PostFinance Ltd. PostFinance Ltd is not responsible for the content.',
                    '', '', '', '', '']
                ]:
            return None
        bookingDate = helpers.DateUtility.strptime(rowValues[0],
                    self.dateFormat)
        if bookingDate < self.dateFrom or self.dateTo < bookingDate:
            raise ValueError('invalid postfinance file: date of row ' + \
                f'{rowValues} is not in expected range '  + \
                f'[{self.dateFrom}, {self.dateTo}]')

        return PostfinanceTransaction(
                bookingDate,
                notificationText = rowValues[1],
                creditAmount = None if rowValues[2] == '' else float(rowValues[2]),
                debitAmount = None if rowValues[3] == '' else float(rowValues[3]),
                value = rowValues[4],
                balance = rowValues[5]
                )

    def prefixValues(self):
        return [self.dateFrom, self.dateTo, self.expectedEntryType,
                self.expectedAccount, self.expectedCurrency]

    def csvRows(self):
        return [[helpers.DateUtility.strftime(t.bookingDate, self.dateFormat),
            t.notificationText,
            '' if t.creditAmount is None else helpers.formatPrice(t.creditAmount),
            '' if t.debitAmount is None else helpers.formatPrice(t.debitAmount),
            t.value, t.balance]
                for t in self]

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
import logging
import os
import math
import tkinter
import functools
import cv2 as cv

from abc import ABC, abstractmethod

from . import gui_components
from . import helpers
from .sheets import ProductSheet

class SheetCategorizer(ABC):
    """
    This class takes a set of active and inactive input sheets plus optionally
    scanned sheets and creates a new set of categorized product sheets where:

    - each scanned sheet is contained exactly once
    - each active sheet is contained if it is not an earlier version of a
      scanned sheet
    - each inactive sheet is contained exactly once
    - new sheets are added if necessary to accomodate the previous / inventory
      quantity of a product
      `
    :param rootDir: root directory of accounting / gen
    :type rootDir: str
    :param db: product database
    :type db: :class:`database.Database`
    :param activeInputSheets: dict of (productId, sheetNumber) -> sheet with
           sheets in the store before accounting / gen
    :type activeInputSheets: dict of (str, str) -> :class:`sheets.ProductSheet`
    :param inactiveInputSheets: dict of (productId, sheetNumber) -> sheet with
           existing inactive sheets before accounting / gen
    :type inactiveInputSheets: dict of (str, str) -> :class:`sheets.ProductSheet`
    :param scannedSheets: dict of (productId, sheetNumber) -> sheet with
           updated versions of (active) sheets from current accounting;
           if None is passed, it is assumed no scanning took place
    :type scannedSheets: dict of (str, str) -> :class:`sheets.ProductSheet`
    :param allowRemoval: allow sheet removal - only allow if all tags have been
        accounted for sure
    :type allowRemoval: boolean
    """
    def __init__(self,
            rootDir,
            db,
            activeInputSheets,
            inactiveInputSheets,
            scannedSheets,
            allowRemoval
            ):
        self.logger = logging.getLogger('tagtrail.sheet_categorizer.SheetCategorizer')
        self.rootDir = rootDir
        self.db = db
        self.activeInputSheets = activeInputSheets
        self.inactiveInputSheets = inactiveInputSheets
        self.scannedSheets = scannedSheets
        self.allowRemoval = allowRemoval
        self._checkPreconditions()
        self.sheets = self.categorize()
        self._checkPostconditions()

    def _checkPreconditions(self):
        productsAddedDuringInventory = []
        for productId, product in self.db.products.items():
            if product.inventoryQuantity and product.addedQuantity:
                productsAddedDuringInventory.append(productId)
        if productsAddedDuringInventory != []:
            raise ValueError(f'Following products have both inventoryQuantity and '
                    'addedQuantity != 0, this is not allowed:\n'
                    f'{productsAddedDuringInventory}\n'
                    'Complete inventory with tagtrail_account first, then '
                    'add products and run tagtrail_gen.')

        productsWithMissingSheetsAdded = []
        for productId, product in self.db.products.items():
            if (self._missingInputSheets(productId) != [] and
                    product.addedQuantity != 0):
                productsWithMissingSheetsAdded.append(productId)
        if productsWithMissingSheetsAdded != []:
            raise ValueError(f'Following products have missing sheets and '
                    'addedQuantity != 0, this is not allowed:\n'
                    f'{productsWithMissingSheetsAdded}\n'
                    'Run tagtrail_ocr --individualScan to add them and '
                    'rerun tagtrail_sanitize and tagtrail_account')

        if self.scannedSheets:
            for s in self.scannedSheets.values():
                if s.unconfidentTags() != []:
                    raise ValueError(f'scanned sheet {s.filename} has unconfident '
                            'tags - run tagtrail_sanitize to correct this')

        for s in self.activeInputSheets.values():
            if s.unconfidentTags() != []:
                raise ValueError(f'active input sheet {s.filename} has '
                        'unconfident tags - this should never happen, please '
                        'file a bug report')

        for s in self.inactiveInputSheets.values():
            if s.unconfidentTags() != []:
                raise ValueError(f'inactive input sheet {s.filename} has '
                        'unconfident tags - this should never happen, please '
                        'file a bug report')

        # check sheet consistency
        for productId, product in self.db.products.items():
            inputSheets = []
            for sheet in self.activeInputSheets.values():
                if sheet.productId() == productId:
                    inputSheets.append(sheet)

            for sheet in self.inactiveInputSheets.values():
                if sheet.productId() == productId:
                    inputSheets.append(sheet)

            if self.scannedSheets is not None:
                for sheet in self.scannedSheets.values():
                    if sheet.productId() == productId:
                        inputSheets.append(sheet)
            if inputSheets == []:
                continue

            if len(set([s.name for s in inputSheets])) != 1:
                raise ValueError(
                        f'{product.id} has different names in different sheets:'
                        f'{[(s.filename, s.name) for s in inputSheets]}')
            if len(set([s.amountAndUnit for s in inputSheets])) != 1:
                raise ValueError(
                        f'{product.id} has different amount and unit in different '
                        f'sheets: {[(s.filename, s.amountAndUnit) for s in inputSheets]}')
            if len(set([s.grossSalesPrice for s in inputSheets])) != 1:
                raise ValueError(
                        f'{product.id} has different price in different sheets:'
                        f'{[(s.filename, s.grossSalesPrice) for s in inputSheets]}')


    def _checkPostconditions(self):
        # make sure sheets relevant for /next are consistent
        names = {}
        prices = {} # productId -> price
        amountsAndUnits = {} # productId -> amountsAndUnits

        # caching already seen sheet filenames of each productId for sensible
        # debug messages
        previousFilenames = {}
        def assertConsistency(isConsistent, productId, testedAttribute, currentFilename):
            if not isConsistent:
                raise ValueError(
                    f'{productId} has different {testedAttribute} in '
                    f'{currentFilename} and '
                    f'{previousFilenames[productId]}')
        for sheet in (self.activeSheetsToBePrinted
                .union(self.activeSheetsFromActive)
                .union(self.activeSheetsFromInactive)
                .union(self.inactiveSheetsFromActive)
                .union(self.inactiveSheetsFromInactive)
                .union(self.missingSheets)):
            if sheet.name not in names.values():
                names[sheet.productId()] = sheet.name
            assertConsistency(names[sheet.productId()] == sheet.name,
                    sheet.productId(), 'name', sheet.filename)
            if sheet.productId() not in prices.values():
                prices[sheet.productId()] = sheet.grossSalesPrice
            assertConsistency(prices[sheet.productId()] == sheet.grossSalesPrice,
                    sheet.productId(), 'prices', sheet.filename)
            if sheet.productId() not in amountsAndUnits.values():
                amountsAndUnits[sheet.productId()] = sheet.amountAndUnit
            assertConsistency(amountsAndUnits[sheet.productId()] == sheet.amountAndUnit,
                    sheet.productId(), 'amountAndUnit', sheet.filename)

            if sheet.productId not in previousFilenames:
                previousFilenames[sheet.productId()] = [sheet.filename]
            else:
                previousFilenames[sheet.productId()].append(sheet.filename)

    @property
    def activeSheetsToBePrinted(self):
        """
        New product sheets to be printed (always active first)
        """
        return set([sheet for sheet in self.sheets
            if sheet.previousState == None and sheet.newState == 'active'])

    @property
    def missingSheets(self):
        """
        Active input sheets that are missing in scanned sheets
        """
        return set([sheet for sheet in self.sheets
            if sheet.previousState == 'active' and sheet.newState == 'missing'])

    @property
    def activeSheetsFromInactive(self):
        """
        Sheets which were inactive until now and should be activated.
        """
        return set([sheet for sheet in self.sheets
            if sheet.previousState == 'inactive' and sheet.newState == 'active'])

    @property
    def activeSheetsFromActive(self):
        """
        Sheets which were already active and should stay active.
        """
        return set([sheet for sheet in self.sheets
            if sheet.previousState == 'active' and sheet.newState == 'active'])

    @property
    def inactiveSheetsFromInactive(self):
        """
        Sheets which were already inactive and should stay inactive.
        """
        return set([sheet for sheet in self.sheets
            if sheet.previousState == 'inactive' and sheet.newState == 'inactive'])

    @property
    def inactiveSheetsFromActive(self):
        """
        Sheets which were active before and should become inactive.
        """
        return set([sheet for sheet in self.sheets
            if sheet.previousState == 'active' and sheet.newState == 'inactive'])

    @property
    def obsoleteSheetsFromActive(self):
        """
        Sheets which were active before and are obsolete now.
        """
        return set([sheet for sheet in self.sheets
            if sheet.previousState == 'active' and sheet.newState == 'obsolete'])

    @property
    def obsoleteSheetsFromInactive(self):
        """
        Sheets which were inactive before and are obsolete now.
        """
        return set([sheet for sheet in self.sheets
            if sheet.previousState == 'inactive' and sheet.newState == 'obsolete'])

    def setNewSheetState(self, sheet, state):
        assert(state in
                ['active', 'inactive', 'missing', 'obsolete'])
        sheet.newState = state

    def setPreviousSheetState(self, sheet, state):
        assert(state in [None, 'active', 'inactive'])
        sheet.previousState = state

    def categorize(self):
        """
        Categorize existing active/inactive sheets and generate new ones
        where necessary to accomodate all product units in the salesmix.
        Remove sheets of products that are not in the database any more.

        Each sheet is assigned a previousState and a newState to be able to
        show the user what to do with each sheet and to prepare the next
        accounting.

        :return: list of sheets, each having a previousState and a newState
        :rtype: list of :class:`sheets.ProductSheet`
        """
        categorizedSheets = []
        # remove sheets of products which have been removed from database
        for filename in os.listdir(f'{self.rootDir}0_input/sheets/active/'):
            productId = ProductSheet.productId_from_filename(filename)
            if productId not in self.db.products:
                assert(productId not in [productId
                    for (productId, _) in self.activeInputSheets.keys()])
                assert(self.allowRemoval)
                sheet = ProductSheet()
                sheet.load(f'{self.rootDir}0_input/sheets/active/{filename}')
                self.setPreviousSheetState(sheet, 'active')
                self.setNewSheetState(sheet, 'obsolete')
                sheet.tooltip = 'product removed from database'
                self.logger.info(f'removing {filename} - product removed from database')
                categorizedSheets.append(sheet)

        for filename in os.listdir(f'{self.rootDir}0_input/sheets/inactive/'):
            productId = ProductSheet.productId_from_filename(filename)
            if productId not in self.db.products:
                assert(productId not in [productId
                    for (productId, _) in self.inactiveInputSheets.keys()])
                assert(self.allowRemoval)
                sheet = ProductSheet()
                sheet.load(f'{self.rootDir}0_input/sheets/inactive/{filename}')
                self.setPreviousSheetState(sheet, 'inactive')
                self.setNewSheetState(sheet, 'obsolete')
                sheet.tooltip = 'product removed from database'
                self.logger.info(f'removing {filename} - product removed from database')
                categorizedSheets.append(sheet)

        # move scanned sheets which should have been inactive (but apparently
        # were not removed after last accounting) to active
        if self.scannedSheets is not None:
            for sheetKey, sheet in self.scannedSheets:
                if sheetKey in self.inactiveInputSheets:
                    self.activeInputSheets[sheetKey] = sheet
                    self.inactiveInputSheets.pop(sheetKey)

        for productId, product in self.db.products.items():
            numTagsNeeded = (product.inventoryQuantity or
                    product.expectedQuantity)

            updatedActiveSheetList = [
                    sheet for (pId, _), sheet in (self.activeInputSheets
                        if self.scannedSheets is None else
                        self.scannedSheets).items()
                        if pId == productId]
            missingInputSheetList = self._missingInputSheets(productId)
            inactiveInputSheetList = [
                    self.inactiveInputSheets[(pId, sheetNumber)]
                    for (pId, sheetNumber) in self.inactiveInputSheets.keys()
                    if pId == productId]

            if numTagsNeeded <= 0:
                # product out of stock but expected to be bought again
                def categorizeSheets(previousState, newState, tooltip, sheets):
                    for s in sheets:
                        self.setPreviousSheetState(s, previousState)
                        self.setNewSheetState(s, newState)
                        s.tooltip = tooltip

                if self.allowRemoval and (updatedActiveSheetList +
                        missingInputSheetList) != []:
                    self.logger.info(f'{product.id} out of stock - deactivating sheets')

                categorizeSheets(previousState = 'active',
                        newState = 'inactive' if self.allowRemoval else 'active',
                        tooltip = 'out of stock' if self.allowRemoval else
                            'out of stock but removal not allowed',
                        sheets = updatedActiveSheetList)
                categorizeSheets(previousState = 'active',
                        newState = 'missing',
                        tooltip = 'out of stock but sheet missing - unable to remove',
                        sheets = missingInputSheetList)
                categorizeSheets(previousState = 'inactive',
                        newState = 'inactive',
                        tooltip = 'out of stock',
                        sheets = inactiveInputSheetList)
            elif self.productNeedsGeneration(product, numTagsNeeded,
                    updatedActiveSheetList + missingInputSheetList +
                    inactiveInputSheetList):
                # product changed - replace all sheets
                if missingInputSheetList != []:
                    raise ValueError(
                            f'Unable to replace sheets for {productId}\n'
                            'Following sheets are missing:\n'
                            f'{[s.filename for s in missingInputSheetList]}\n'
                            'Run tagtrail_ocr --individualScan to add them and '
                            'rerun tagtrail_sanitize and tagtrail_account')

                if not self.allowRemoval and (updatedActiveSheetList != [] or
                        inactiveInputSheetList != []):
                    raise ValueError(
                            f'Unable to replace sheets for {productId}\n'
                            'Run tagtrail_gen with --allowRemoval option '
                            'if you are sure no new tags have been added since '
                            'last accounting. If not, do an accounting before '
                            'changing products.')

                tooltip = 'product changed, replacing all sheets'
                for s in updatedActiveSheetList:
                    self.setPreviousSheetState(s, 'active')
                    self.setNewSheetState(s, 'obsolete')
                    s.tooltip = tooltip
                for s in inactiveInputSheetList:
                    self.setPreviousSheetState(s, 'inactive')
                    self.setNewSheetState(s, 'obsolete')
                    s.tooltip = tooltip

                numSheetsNeeded = math.ceil(numTagsNeeded /
                        ProductSheet.maxQuantity())
                maxNumSheets = self.db.config.getint('tagtrail_gen',
                        'max_num_sheets_per_product')
                if numSheetsNeeded > maxNumSheets:
                    raise ValueError(f'Quantity of {productId} is too high, '
                            f'would need {numSheetsNeeded}, '
                            f'max {maxNumSheets} are allowed')
                # one based, as this goes out to customers
                for sheetNumber in range(1, numSheetsNeeded+1):
                    newSheet = SheetCategorizer.generateProductSheet(self.db,
                            product, sheetNumber)
                    self.setPreviousSheetState(newSheet, None)
                    self.setNewSheetState(newSheet, 'active')
                    newSheet.tooltip = tooltip
                    categorizedSheets.append(newSheet)
            else:
                # product did not change and some existing sheets need to be
                # active
                generatedSheetList = self.activateAndReplaceIndividualSheets(product, numTagsNeeded,
                        updatedActiveSheetList, missingInputSheetList,
                        inactiveInputSheetList)
                categorizedSheets += generatedSheetList

            categorizedSheets += updatedActiveSheetList
            categorizedSheets += missingInputSheetList
            categorizedSheets += inactiveInputSheetList

        for s in categorizedSheets:
            assert(hasattr(s, 'previousState'))
            assert(hasattr(s, 'newState'))
            assert(hasattr(s, 'tooltip'))
        return sorted(categorizedSheets, key=lambda sheet: sheet.filename)

    def _missingInputSheets(self, productId):
        if self.scannedSheets is None:
            return []
        return [self.activeInputSheets[(pId, sheetNumber)]
                for (pId, sheetNumber) in self.activeInputSheets.keys()
                if (pId == productId
                    and (pId, sheetNumber) not in self.scannedSheets)]

    def productNeedsGeneration(self, product, numTagsNeeded, inputSheets):
        """
        Has `product` changed in a way that all sheets need to be regenerated?

        This is the case if at least one of the following criteria is true:
        * no previous sheets exist
        * amount or unit were changed compared to existing product sheets
        * price changed more than `max_neglectable_price_change_percentage`
        (check config/tagtrail.cfg) compared to existing product sheets
        * existing sheets don't provide enough room for tagging the
        product.expectedQuantity and the price changed (even a little)

        :param product: product to check
        :type product: :class:`database.Product`
        :param numTagsNeeded: number of tags needed for current stock
        :type numTagsNeeded: int
        :param inputSheets: list of all existing sheets of the product
        :type inputSheets: list of :class: `sheets.ProductSheet`
        :return: True if sheets need to be regenerated
        :rtype: bool
        """
        if inputSheets == []:
            self.logger.info(
                    f'regenerate sheets of {product.id}: no previous sheets exist')
            return True

        inputSheet = inputSheets[0]

        if product.amountAndUnit.upper() != inputSheet.amountAndUnit.upper():
            self.logger.info(
                    f'regenerate sheets of {product.id}: amount/unit changed '
                    f'from {inputSheet.amountAndUnit} to '
                    f'{product.amountAndUnit}')
            return True

        priceChangeThreshold = self.db.config.getint('tagtrail_gen',
                'max_neglectable_price_change_percentage')
        if (abs(product.grossSalesPrice()-inputSheet.grossSalesPrice) /
                inputSheet.grossSalesPrice > priceChangeThreshold / 100):
            self.logger.info(
                    f'regenerate sheets of {product.id}: price changed more '
                    f'than {priceChangeThreshold}%, from '
                    f'{inputSheet.grossSalesPrice} to '
                    f'{product.grossSalesPrice()}')
            return True

        numFreeTags = 0
        for s in inputSheets:
            numFreeTags += len(s.emptyDataBoxes())
        if (product.grossSalesPrice() != inputSheet.grossSalesPrice and
                numFreeTags < numTagsNeeded):
            self.logger.info(
                    f'regenerate sheets of {product.id}: '
                    'not enough free tags and price changed '
                    f'from {inputSheet.grossSalesPrice} to '
                    f'{product.grossSalesPrice()}')
            return True

        return False

    def activateAndReplaceIndividualSheets(self, product, numTagsNeeded,
            updatedActiveInputSheets, missingInputSheets, inactiveInputSheets):
        """
        Activate inactive sheets and add new sheets to print until enough room
        is available to accomodate the expected quantity

        If self.allowRemoval == True, full sheets are removed, active ones can
        be deactivated and existing sheets replaced where necessary.

        No missingInputSheets are allowed if product.addedQuantity > 0.

        :param product: product to consider
        :type product: :class: `database.Product`
        :param numTagsNeeded: number of tags needed for the product
        :param updatedActiveInputSheets: list of previously active sheets of product in 0_input
        :type updatedActiveInputSheets: list of :class: `sheets.ProductSheet`
        :param missingInputSheets: list of missing active sheets of product in 0_input
        :type missingInputSheets: list of :class: `sheets.ProductSheet`
        :param inactiveInputSheets: list of previously inactive sheets of product in 0_input
        :type inactiveInputSheets: list of :class: `sheets.ProductSheet`
        :return: a list of generated sheets
        :rtype: list of :class: `sheets.ProductSheet`
        """
        # check if expected quantity is feasible if all sheets are printed new
        numSheetsNeeded = math.ceil(numTagsNeeded /
                ProductSheet.maxQuantity())
        maxNumSheets = self.db.config.getint('tagtrail_gen',
                'max_num_sheets_per_product')
        self.logger.debug(f'activateAndReplaceIndividualSheets for {product.id}')
        self.logger.debug(f'numSheetsNeeded for {product.id} = {numSheetsNeeded}')
        if maxNumSheets < numSheetsNeeded:
            raise ValueError(f'Quantity of {product.id} is too high, '
                    f'would need {numSheetsNeeded}, max '
                    f'{maxNumSheets} are allowed')

        def sortedSheetsFullFirst(sheets):
            return sorted(sheets, key = lambda s: len(s.emptyDataBoxes()))

        # first, use active sheets without replacement
        numFreeTags = 0
        for s in sortedSheetsFullFirst(updatedActiveInputSheets):
            if s.isFull():
                if self.allowRemoval:
                    self.setPreviousSheetState(s, 'active')
                    self.setNewSheetState(s, 'obsolete')
                    s.tooltip = 'sheet is full'
                else:
                    self.setPreviousSheetState(s, 'active')
                    self.setNewSheetState(s, 'active')
                    s.tooltip = 'sheet is full, but removal is forbidden'
            elif numFreeTags < numTagsNeeded:
                self.setPreviousSheetState(s, 'active')
                self.setNewSheetState(s, 'active')
                s.tooltip = 'sheet has free tags that can be used'
                numFreeTags += len(s.emptyDataBoxes())
            else:
                if self.allowRemoval:
                    self.setPreviousSheetState(s, 'active')
                    self.setNewSheetState(s, 'inactive')
                    s.tooltip = 'sheet has free tags, but they are not needed'
                else:
                    self.setPreviousSheetState(s, 'active')
                    self.setNewSheetState(s, 'active')
                    s.tooltip = ('sheet has free tags that are not needed, '
                            'but removal is forbidden')

        # activate inactive sheets if necessary
        for s in sortedSheetsFullFirst(inactiveInputSheets):
            if s.isFull():
                if self.allowRemoval:
                    self.setPreviousSheetState(s, 'inactive')
                    self.setNewSheetState(s, 'obsolete')
                    s.tooltip = 'sheet is full'
                else:
                    self.setPreviousSheetState(s, 'inactive')
                    self.setNewSheetState(s, 'inactive')
                    s.tooltip = 'sheet is full, but removal is forbidden'
            elif numFreeTags < numTagsNeeded:
                self.setPreviousSheetState(s, 'inactive')
                self.setNewSheetState(s, 'active')
                s.tooltip = 'sheet has free tags that can be used'
                numFreeTags += len(s.emptyDataBoxes())
            else:
                self.setPreviousSheetState(s, 'inactive')
                self.setNewSheetState(s, 'inactive')
                s.tooltip = 'sheet has free tags, but they are not needed'

        # missing sheets cannot be replaced
        for s in missingInputSheets:
            self.setPreviousSheetState(s, 'active')
            self.setNewSheetState(s, 'missing')
            s.tooltip = 'out of stock but sheet missing - unable to remove'

        if numFreeTags >= numTagsNeeded:
            return []

        # generate new sheets until we have enough free tags if necessary
        activeInputSheetsByNumber = {ProductSheet.parse_sheetNumber(self.db, s.sheetNumber): s
                for s in updatedActiveInputSheets}
        inactiveInputSheetsByNumber = {ProductSheet.parse_sheetNumber(self.db, s.sheetNumber): s
                for s in inactiveInputSheets}
        newSheetNumbers = [n for n in range(1, maxNumSheets+1)
                if not (
                    n in activeInputSheetsByNumber.keys()
                    or n in inactiveInputSheetsByNumber.keys()
                    # missing sheets cannot be replaced and are assumed to be full
                    or n in [ProductSheet.parse_sheetNumber(self.db,
                        s.sheetNumber) for s in missingInputSheets])]
        if (numFreeTags + len(newSheetNumbers)*ProductSheet.maxQuantity() <
                numTagsNeeded):
            if not self.allowRemoval:
                raise ValueError('Unable to replace sheets for '
                        f'{product.id}\n'
                        'Run tagtrail_gen with --allowRemoval option if '
                        'you are sure no new tags have been added since '
                        'last accounting. If you are not sure, do an accounting '
                        'before adding new products.')
            if missingInputSheets != []:
                raise ValueError(f'{product.id} would need to replace '
                        'some sheets but following sheets are missing:\n'
                        f'{missingInputSheets}\n'
                        'Run tagtrail_ocr --individualScan to add them and'
                        'rerun tagtrail_sanitize and tagtrail_account')

        sheetNumbersInReplacementOrder = newSheetNumbers.copy()
        if self.allowRemoval:
            sheetNumbersInReplacementOrder += [
                    ProductSheet.parse_sheetNumber(self.db, s.sheetNumber)
                    for s in sortedSheetsFullFirst(
                        updatedActiveInputSheets + inactiveInputSheets)
                    ]

        self.logger.debug(f'activeInputSheetsByNumber: {activeInputSheetsByNumber}')
        self.logger.debug(f'inactiveInputSheetsByNumber: {inactiveInputSheetsByNumber}')
        self.logger.debug(f'newSheetNumbers: {newSheetNumbers}')
        self.logger.debug(f'sheetNumbersInReplacementOrder: {sheetNumbersInReplacementOrder}')

        generatedSheets = []
        for sheetNumber in sheetNumbersInReplacementOrder:
            self.logger.debug(f'numFreeTags = {numFreeTags}')
            self.logger.debug(f'numTagsNeeded = {numTagsNeeded}')
            if numFreeTags >= numTagsNeeded:
                break

            if sheetNumber not in newSheetNumbers:
                self.logger.debug(f'sheet number {sheetNumber} is not new')
                s = None
                if sheetNumber in activeInputSheetsByNumber:
                    s = activeInputSheetsByNumber[sheetNumber]
                    self.setPreviousSheetState(s, 'active')
                elif sheetNumber in inactiveInputSheetsByNumber:
                    s = inactiveInputSheetsByNumber[sheetNumber]
                    self.setPreviousSheetState(s, 'inactive')
                else:
                    assert(False, 'replaced sheet must be active or inacive')
                self.setNewSheetState(s, 'obsolete')
                s.tooltip = 'replaced by new sheet'
                numFreeTags -= len(s.emptyDataBoxes())

            newSheet = SheetCategorizer.generateProductSheet(self.db, product,
                    sheetNumber)
            self.setPreviousSheetState(newSheet, None)
            self.setNewSheetState(newSheet, 'active')
            newSheet.tooltip = 'newly generated'
            self.logger.info(f'generate empty sheet {newSheet.filename} '
                    'to create enough free tags')
            generatedSheets.append(newSheet)
            numFreeTags += ProductSheet.maxQuantity()

        assert(numFreeTags >= numTagsNeeded)
        return generatedSheets

    def writeSheets(self):
        generatedSheetsDir = f'{self.rootDir}1_generatedSheets/'
        outputDir = f'{self.rootDir}5_output/'
        sheetsOutputDir = f'{outputDir}sheets/'
        activeSheetsOutputDir = f'{sheetsOutputDir}active/'
        inactiveSheetsOutputDir = f'{sheetsOutputDir}inactive/'
        obsoleteSheetsOutputDir = f'{sheetsOutputDir}obsolete/'
        removedSheetsOutputDir = f'{obsoleteSheetsOutputDir}removed/'
        replacedSheetsOutputDir = f'{obsoleteSheetsOutputDir}replaced/'

        # create directories
        helpers.recreateDir(generatedSheetsDir)
        helpers.recreateDir(outputDir)
        helpers.recreateDir(sheetsOutputDir)
        helpers.recreateDir(activeSheetsOutputDir)
        helpers.recreateDir(inactiveSheetsOutputDir)
        helpers.recreateDir(obsoleteSheetsOutputDir)
        helpers.recreateDir(removedSheetsOutputDir)
        helpers.recreateDir(replacedSheetsOutputDir)

        # generate new sheets
        for sheet in self.activeSheetsToBePrinted:
            imgPath = f'{generatedSheetsDir}{sheet.productId()}_{sheet.sheetNumber}.jpg'
            if cv.imwrite(imgPath, sheet.createImg()) is True:
                self.logger.info(f'generated sheet {imgPath}')
            else:
                raise ValueError(f'failed to generate sheet {imgPath}')

        # store output sheets
        priceChangeThreshold = self.db.config.getint('tagtrail_gen',
                'max_neglectable_price_change_percentage') / 100
        for sheet in (self.activeSheetsToBePrinted
                .union(self.activeSheetsFromActive)
                .union(self.activeSheetsFromInactive)
                .union(self.missingSheets)):
            product = self.db.products[sheet.productId()]
            assert(abs(sheet.grossSalesPrice - product.grossSalesPrice()) /
                    sheet.grossSalesPrice < priceChangeThreshold)
            sheet.store(activeSheetsOutputDir)
        for sheet in (self.inactiveSheetsFromActive
                .union(self.inactiveSheetsFromInactive)):
            sheet.store(inactiveSheetsOutputDir)
        for sheet in (self.obsoleteSheetsFromActive
                .union(self.obsoleteSheetsFromInactive)):
            if os.path.exists(f'{activeSheetsOutputDir}{sheet.filename}'):
                sheet.store(replacedSheetsOutputDir)
            else:
                sheet.store(removedSheetsOutputDir)

        # TODO: print tooltip / sheet list once done
        # needs gettext to reuse GUI strings properly
        # only show missing sheets: during tagtrail_account

    @classmethod
    def generateProductSheet(cls, db, product, sheetNumber):
        """
        Generate a new :class: `sheets.ProductSheet`

        :param db: database to read currency and sheet number format from
        :param product: the product to generate a sheet for
        :type product: :class: `database.Product`
        :param sheetNumber: number of the sheet
        :type sheetNumber: int
        :return: a new product sheet
        :rtype: :class: `sheets.ProductSheet`
        """
        sheet = ProductSheet()
        sheet.name = product.description
        sheet.amountAndUnit = product.amountAndUnit
        sheet.grossSalesPrice = helpers.formatPrice(
                product.grossSalesPrice(),
                db.config.get('general', 'currency'))
        sheet.sheetNumber = db.config.get('tagtrail_gen',
                'sheet_number_string').format(sheetNumber=str(sheetNumber))
        return sheet

class CategorizerGUI(gui_components.BaseGUI):
    padx = 5
    pady = 5
    scanPostfix = '_normalized_scan.jpg'

    def __init__(self,
            model):
        """
        Initialize GUI for a model with an attached :class: `SheetCategorizer`
        """
        self.model = model
        self.logger = logging.getLogger('tagtrail.sheet_categorizer.CategorizerGUI')

        self.productFrame = None
        self.activeFrame = None
        self.inactiveFrame = None
        self.obsoleteFrame = None
        self.scrollbarY = None
        self.initializedSheets = False

        width = self.model.db.config.getint('general', 'screen_width')
        width = None if width == -1 else width
        height = self.model.db.config.getint('general', 'screen_height')
        height = None if height == -1 else height
        super().__init__(width, height)

    def populateRoot(self):
        if not self.initializedSheets:
            for sheet in self.model.sheetCategorizer.sheets:
                sheet.userAsksForReplacement = tkinter.BooleanVar()
            self.initializedSheets = True

        if self.productFrame is None:
            self.productFrame = gui_components.ScrollableFrame(self.root,
                    relief=tkinter.GROOVE)
        self.productFrame.config(width = self.width - self.buttonFrameWidth,
                    height = self.height)
        self.productFrame.place(x=0, y=0)

        if self.activeFrame is None:
            self.activeFrame = tkinter.Frame(self.productFrame.scrolledwindow, relief=tkinter.GROOVE)
        for w in self.activeFrame.winfo_children():
            w.destroy()
        activeLabel = tkinter.Label(self.activeFrame, text='Active sheets')
        activeLabel.pack(side=tkinter.TOP, fill=tkinter.X, padx = self.padx, pady = self.pady)
        gui_components.ToolTip(activeLabel,
                ('These sheets should be available for customers to tag '
                '(physical printouts in the store).'))
        self.populateActiveFrame()

        if self.inactiveFrame is None:
            self.inactiveFrame = tkinter.Frame(self.productFrame.scrolledwindow, relief=tkinter.GROOVE)
        for w in self.inactiveFrame.winfo_children():
            w.destroy()
        inactiveLabel = tkinter.Label(self.inactiveFrame, text='Inactive sheets')
        inactiveLabel.pack(side=tkinter.TOP, fill=tkinter.X, padx = self.padx, pady = self.pady)
        gui_components.ToolTip(inactiveLabel,
                ('These sheets should be kept somewhere out of customers'
                ' reach, ready for reuse when new stock arrives.'))
        self.populateInactiveFrame()

        if self.obsoleteFrame is None:
            self.obsoleteFrame = tkinter.Frame(self.productFrame.scrolledwindow, relief=tkinter.GROOVE)
        for w in self.obsoleteFrame.winfo_children():
            w.destroy()
        obsoleteLabel = tkinter.Label(self.obsoleteFrame, text='Obsolete sheets')
        obsoleteLabel.pack(side=tkinter.TOP, fill=tkinter.X, padx = self.padx, pady = self.pady)
        gui_components.ToolTip(obsoleteLabel,
                ('These sheets are full and should be removed and destroyed '
                'or archived.'))
        self.populateObsoleteFrame()

        maxHeight = max(self.activeFrame.winfo_reqheight(),
                self.inactiveFrame.winfo_reqheight(),
                self.obsoleteFrame.winfo_reqheight())
        maxWidth = max(self.activeFrame.winfo_reqwidth(),
                self.inactiveFrame.winfo_reqwidth(),
                self.obsoleteFrame.winfo_reqwidth())

        self.activeFrame.place(x = 0, y = 0,
                width = maxWidth, height = maxHeight)
        self.inactiveFrame.place(x = maxWidth, y = 0,
                width = maxWidth, height = maxHeight)
        self.obsoleteFrame.place(x = 2*maxWidth, y = 0,
                width = maxWidth, height = maxHeight)
        self.productFrame.scrolledwindow.config(width = 3 * maxWidth,
                height = maxHeight)

        buttons = []
        buttons.append(('cancelAndQuit', 'Cancel', self.cancelAndQuit))
        buttons.append(('saveAndQuit', 'Save and Quit', self.saveAndQuit))
        self.addButtonFrame(buttons)
        self.buttons['saveAndQuit'].focus_set()

    def populateActiveFrame(self):
        self._addCategoryFrame(self.activeFrame, 'New', None, 'active',
                False, False,
                ('These sheets belong to new products - print them out and bring them to the store.')
                ).config(background='tan1')

        self._addCategoryFrame( self.activeFrame, 'Activated', 'inactive',
                'active', False, self.model.sheetCategorizer.allowRemoval,
                ('Formerly inactive sheets that should be available to '
                'customers again. Bring them to the store.')
                ).config(background='tan1')

        self._addCategoryFrame(self.activeFrame, 'Unchanged', 'active',
                'active', False, self.model.sheetCategorizer.allowRemoval,
                ('Active sheets that are already available in the store. '
                 'Nothing to do.')
                ).config(background='green')

    def populateInactiveFrame(self):
        self._addCategoryFrame(self.inactiveFrame, 'New', 'active',
                'inactive', True, False,
                ('These sheets became inactive (product sold out).\n'
                'Remove them from the store and keep them somewhere for later '
                'reuse.')
                ).config(background='tan1')

        self._addCategoryFrame(self.inactiveFrame, 'Unchanged', 'inactive',
                'inactive', True, False,
                ('These sheets were already inactive after last accounting, '
                'just keep them for later reuse.')
                ).config(background='green')

    def populateObsoleteFrame(self):
        self._addCategoryFrame(self.obsoleteFrame, 'Removed from active',
                'active', 'obsolete', False, False,
                ('These formerly active sheets are not needed any more. '
                'Remove them from the store and archive or throw them away.'),
                ).config(background='tan1')

        self._addCategoryFrame(self.obsoleteFrame, 'Removed from inactive',
                'inactive', 'obsolete', False, False,
                ('These previously inactive sheets cannot be used any more. '
                'Archive or throw them away.'),
                ).config(background='tan1')

    def _addCategoryFrame(self, parent, title, previousState, newState,
            addActivationButton, addReplacementCheckbox, tooltip):
        """
        Add a frame with all sheets with a given previous and new state, plus
        optional buttons for the user to change the newState of each sheet.

        :param parent: parent widget
        :type parent: tkinter widget
        :param title: title of the frame
        :type title: str
        :param previousState: previous state identifier
        :type previousState: str
        :param newState: new state identifier
        :type newState: str
        :param tooltip: tooltip describing the category and necessary actions
        to be taken for sheets in this category to the user
        :type tooltip: str
        :param addActivationButton: add a button to set the newState 'active'
        :type addActivationButton: bool
        :param addReplacementCheckbox: add a checkbox - if set, the sheet will be
        replaced (and keep its state)
        :type addReplacementCheckbox: bool
        :return: created frame
        :rtype: tkinter.Frame
        """
        frame = tkinter.Frame(parent)
        frameLabel = tkinter.Label(frame, text=title)
        frameLabel.grid(row=0, column=0)
        gui_components.ToolTip(frameLabel, tooltip)

        rowIdx = 0
        for sheet in self.model.sheetCategorizer.sheets:
            if sheet.previousState != previousState or sheet.newState != newState:
                continue
            rowIdx += 1
            label = tkinter.Label(frame, text=sheet.filename)
            label.grid(row=rowIdx, column=0, padx=self.padx, pady=self.pady)
            gui_components.ToolTip(label, sheet.tooltip)

            if addActivationButton:
                b = tkinter.Button(frame, text='Activate')
                command = functools.partial(self.__activateSheet, sheet)
                b.bind('<Button-1>', command)
                b.bind('<Return>', command)
                b.grid(row=rowIdx, column=1)

            if addReplacementCheckbox:
                b = tkinter.Checkbutton(frame, text='Replace',
                        variable=sheet.userAsksForReplacement, onvalue=True,
                        offvalue=False)
                b.grid(row=rowIdx, column=2, padx = self.padx, pady = self.pady)
                gui_components.ToolTip(b,
                    'Replace sheet with a new one')

        frame.pack(side=tkinter.TOP, fill=tkinter.X, padx = self.padx, pady = self.pady)
        frame.config(relief=tkinter.GROOVE, bd=2)
        frame.update()
        return frame

    def __activateSheet(self, sheet, event):
        """
        Set the newState of sheet to active
        This method is intended to be passed to buttons

        :param sheet: sheet
        :type sheet: :class:`ProductSheet`
        :param event: tkinter event
        """
        sheet.newState = 'active'
        sheet.tooltip = f'User activated (original tooltip: {sheet.tooltip})'
        self.populateRoot()

    def saveAndQuit(self, event = None):
        try:
            newSheets = []
            for sheet in self.model.sheetCategorizer.sheets:
                if sheet.userAsksForReplacement.get():
                    self.logger.info(f'replace sheet selected by user: {sheet.filename}')
                    self.model.sheetCategorizer.setNewSheetState(sheet, 'obsolete')
                    newSheet = ProductSheet.empty_from_sheet(sheet)
                    self.model.sheetCategorizer.setPreviousSheetState(newSheet,
                            None)
                    self.model.sheetCategorizer.setNewSheetState(newSheet,
                            'active')
                    newSheets.append(newSheet)

            self.model.sheetCategorizer.sheets += newSheets
            self.model.save()
        finally:
            self.root.quit()

    def cancelAndQuit(self, event = None):
        self.root.quit()

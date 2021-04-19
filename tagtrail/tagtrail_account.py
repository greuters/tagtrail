# -*- coding: utf-8 -*-
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
import argparse
from abc import ABC, abstractmethod
import tkinter
from tkinter import messagebox
import itertools
import datetime
import os
import shutil
import csv
import copy
import sys
import functools
import cv2 as cv

from . import helpers
from . import gui_components
from .sheets import ProductSheet
from . import database
from . import eaternity

class TagCollector(ABC):
    """
    TagCollector reads all sanitized product sheets and compares them to
    those of the last accounting. It collects all newly added tags per product.
    """
    skipCnt = 1
    csvDelimiter = ';'
    quotechar = '"'
    newline = ''

    def __init__(self,
            inputSheetsPath,
            scannedSheetsPath,
            accountingDate,
            db, log = helpers.Log()):
        self.log = log
        self.db = db
        self.inputSheetsPath = inputSheetsPath
        self.scannedSheetsPath = scannedSheetsPath
        self.accountingDate = accountingDate
        self.activeInputSheets = self.loadProductSheets(
                f'{self.inputSheetsPath}active/')
        self.inactiveInputSheets = self.loadProductSheets(
                f'{self.inputSheetsPath}inactive/')
        self.scannedSheets = self.loadProductSheets(
                self.scannedSheetsPath)
        self.checkPriceConsistency()
        self.checkAmountAndUnitConsistency()
        self.checkInputSheetsConsistency()
        self.checkScannedSheetsKnown()
        self.newTagsPerProduct = self.collectNewTagsPerProduct()

    def taggedGrossSalesPrice(self, productId):
        return self.__sheetGrossSalesPrice(productId, self.scannedSheets)

    def __sheetGrossSalesPrice(self, productId, sheets):
        prices = [s.grossSalesPrice
                  for (pId, _), s in sheets.items()
                  if pId == productId]
        if prices:
            if len(set(prices)) != 1:
                raise AssertionError(f'''should have exactly one price per
                product, but {productId} has several: {prices}''')
            return prices[0]
        else:
            return None

    def __sheetAmountAndUnit(self, productId, sheets):
        amountAndUnits = [s.amountAndUnit
                for (pId, _), s in sheets.items()
                if pId == productId]
        if amountAndUnits:
            if len(set(amountAndUnits)) != 1:
                raise AssertionError(f'''should have exactly one amount per
                product, but {productId} has several: {amountAndUnits}''')
            return amountAndUnits[0]
        else:
            return None

    def numNewTags(self, productId, memberIds):
        """
        Count the number of new tags sticked  on the relevant product by one of
        the specified members.

        :param productId: id of the product to count
        :type productId: str
        :param memberIds: list of memberIds to count
        :type memberIds: [str]
        :return: number of tags added by one of these members
        :rtype: int
        """
        if productId in self.newTagsPerProduct:
            tags = self.newTagsPerProduct[productId]
            numTags = sum([1 for tag in tags if tag in memberIds])
            self.log.debug(f'tags={tags}, productId={productId}, ' + \
                    f'memberIds={memberIds}, numTags={numTags}')
            return numTags
        else:
            return 0

    def newTags(self, productId, sheetNumber):
        """
        Find all tags on a scanned sheet which were not yet there on the
        corresponding input sheet.

        :param productId: id of the product to process
        :type productId: str
        :param sheetNumber: number of the sheet to process
        :type sheetNumber: str
        :return: list of new tags (memberIds)
        :rtype: list of str
        """
        key = (productId, sheetNumber)
        inputTags = None
        if key in self.activeInputSheets:
            inputTags = self.activeInputSheets[key].confidentTags()
        elif key in self.inactiveInputSheets:
            inputTags = self.inactiveInputSheets[key].confidentTags()
        assert(inputTags is not None)

        scannedTags = self.scannedSheets[key].confidentTags()
        assert(len(inputTags) == len(scannedTags))
        self.log.debug(f'inputTags: {inputTags}')
        self.log.debug(f'scannedTags: {scannedTags}')

        changedIndices = [idx for idx, tag in enumerate(inputTags)
                if scannedTags[idx] != tag]
        self.log.debug(f'changedIndices: {changedIndices}')
        offendingDataboxes = [f'dataBox{idx}' for idx in changedIndices if inputTags[idx] != '']
        if offendingDataboxes:
            self.log.error(f'offendingDataboxes: {offendingDataboxes}')
            inputSheetFilename = (self.inputSheetsPath
                + ('active/' if key in self.activeInputSheets else 'inactive/')
                + f'{productId}_{sheetNumber}.csv')
            raise ValueError(f'''
                    Already accounted tags were changed in the current
                    accounting.\n\n
                    This situation indicates a tagging error and has to be
                    resolved manually by correcting this file:\n\n
                    {self.scannedSheetsPath}{productId}_{sheetNumber}.csv\n\n
                    Offending data boxes:\n\n
                    {offendingDataboxes}\n\n
                    Corresponding file from last accounting:\n\n
                    {inputSheetFilename}''')

        return list(map(lambda idx: scannedTags[idx], changedIndices))

    def collectNewTagsPerProduct(self):
        """
        Find all new tags for each product.

        :return: {productId -> [memberId]}
        :rtype: {str -> [str]}
        """
        newTags = {}
        for key in self.scannedSheets.keys():
            newTags[key] = self.newTags(key[0], key[1])

            unknownTags = list(filter(
                    lambda tag: tag and tag not in self.db.members.keys(),
                    newTags[key]))
            if unknownTags:
                raise ValueError(f"""
                    {self.scannedSheetsPath}{key[0]}_{key[1]}.csv
                    contains a new tag for non-existent members '{unknownTags}'.
                    Run tagtrail_sanitize before tagtrail_account!""")
            self.log.debug(f'newTags[{key}]={newTags[key]}')

        newTagsPerProduct = {}
        for productId, sheetNumber in self.scannedSheets.keys():
            if productId not in newTagsPerProduct:
                newTagsPerProduct[productId] = []
            newTagsPerProduct[productId] += newTags[productId, sheetNumber]
        self.log.debug(f'newTagsPerProduct: {newTagsPerProduct.items()}')
        return newTagsPerProduct

    def loadProductSheets(self, path):
        """
        Load product sheets in a directory and check the following properties:
        * productId exists in database
        * filename is consistent with content (productId and sheetNumber)
        * file is fully sanitized
        * product sheet is loaded only once

        :param path: directory to load product sheets from
        :type path: str
        :return: dict of (productId, sheetNumber) -> sheet
        :rtype: dict of (str, str) -> :class:`sheets.ProductSheet`
        """
        self.log.info(f'collecting tags in {path}')
        csvFilenames = helpers.sortedFilesInDir(path, ext = '.csv')
        if not csvFilenames:
            return {}

        productSheets = {}
        for filename in csvFilenames:
            productId = ProductSheet.productId_from_filename(filename)
            sheetNumber = ProductSheet.sheetNumber_from_filename(filename)
            self.log.debug(f'productId={productId}, sheetNumber={sheetNumber}')
            sheet = ProductSheet()
            sheet.load(path+filename)
            if productId not in self.db.products:
                raise ValueError(f'{productId} has a sheet, but is missing in '
                'database. Add it to products.csv')
            if sheet.productId() != productId:
                raise ValueError(f'{path+filename} is invalid.\n'
                        f'{sheet.productId()} != {productId}')
            if sheet.sheetNumber != sheetNumber:
                raise ValueError(f' {path+filename} is invalid.\n'
                        f'{sheet.sheetNumber} != {sheetNumber}')
            if sheet.unconfidentTags():
                raise ValueError(
                        f'{path+filename} is not properly sanitized.\n'
                        'Run tagtrail_sanitize before tagtrail_account!')
            if (productId, sheetNumber) in productSheets:
                raise ValueError(
                    f'{(productId, sheetNumber)} exists more than once')
            productSheets[(productId, sheetNumber)] = sheet
        return productSheets

    def checkPriceConsistency(self):
        """
        All sheets of one product (scanned and already accounted ones from
        active/inactive input) must have the same price.
        Check and abort if this is not the case.
        """
        for productId in self.db.products.keys():
            activeInputPrice = self.__sheetGrossSalesPrice(productId,
                    self.activeInputSheets)
            inactiveInputPrice = self.__sheetGrossSalesPrice(productId,
                    self.inactiveInputSheets)
            scannedPrice = self.__sheetGrossSalesPrice(productId,
                    self.scannedSheets)
            prices = set([activeInputPrice, inactiveInputPrice, scannedPrice])
            if None in prices:
                prices.remove(None)
            if 1 < len(prices):
                raise ValueError(f'''
                        {productId}: already accounted sheets have another
                        price then scanned ones (scanned: {scannedPrice},
                        activeInput: {activeInputPrice},
                        inactiveInput: {inactiveInputPrice})''')

    def checkAmountAndUnitConsistency(self):
        """
        All sheets of one product (scanned and already accounted ones from
        active/inactive input) must have the same amount and unit.
        Check and abort if this is not the case.
        """
        for productId in self.db.products.keys():
            activeInputAmount = self.__sheetAmountAndUnit(productId,
                    self.activeInputSheets)
            inactiveInputAmount = self.__sheetAmountAndUnit(productId,
                    self.inactiveInputSheets)
            scannedAmount = self.__sheetAmountAndUnit(productId,
                    self.scannedSheets)
            amounts = set([activeInputAmount, inactiveInputAmount, scannedAmount])
            if None in amounts:
                amounts.remove(None)
            if 1 < len(amounts):
                raise ValueError(f'''
                        {productId}: already accounted sheets have another
                        amount then scanned ones (scanned: {scannedAmount},
                        activeInput: {activeInputAmount},
                        inactiveInput: {inactiveInputAmount})''')

    def checkInputSheetsConsistency(self):
        """
        Each sheet should exist only once as either active or inactive
        input sheet, and at least one sheet should exist for each product
        in the database which has any stock left.
        Check and abort if this is not the case.
        """
        for productId, product in self.db.products.items():
            activeSheetNumbers = set([sheetNumber
                for (pId, sheetNumber) in self.activeInputSheets.keys()
                if pId == productId])

            inactiveSheetNumbers = set([sheetNumber
                for (pId, sheetNumber) in self.inactiveInputSheets.keys()
                if pId == productId])

            duplicates = activeSheetNumbers.intersection(inactiveSheetNumbers)
            if duplicates != set():
                raise ValueError(f'''
                        Duplicate input sheets exist for {productId}:
                        {duplicates}. Delete the sheets in
                        {self.inputSheetsPath}/active/ or
                        {self.inputSheetsPath}/inactive/
                        ''')

            if product.expectedQuantity <= 0:
                continue

            if activeSheetNumbers.union(inactiveSheetNumbers) == set():
                raise ValueError(f'''
                        No input sheet exists for {productId}.
                        Run tagtrail_gen to generate sheets for newly added
                        products.
                        ''')

    def checkScannedSheetsKnown(self):
        """
        For each scanned sheet, a corresponding active (or inactive, if the
        user forgot to take it out last time) input sheet should exist.

        Check and abort if this is not the case.
        """
        for key, sheet in self.scannedSheets.items():
            if (key not in self.activeInputSheets
                    and key not in self.inactiveInputSheets):
                raise ValueError(f'''
                        No input sheet exists for scanned sheet
                        '{sheet.filename}'.
                        Check if you forgot to remove the sheet during last
                        accounting (it would be in
                        5_output/sheets/obsolete/removed of the last accounting
                        folder).\n
                        If this is the case, delete the scanned sheet in
                        2_taggedProductSheets.\n
                        If not, your best option to recover is to
                        copy the scanned sheet
                        2_taggedProductSheets/{sheet.filename}
                        to {self.inputSheetsPath}active/
                        This way customers are not billed wrongly, while
                        you'll loose the total price of the tagged products
                        during next inventory.
                        ''')

class GUI(gui_components.BaseGUI):
    scanPostfix = '_normalized_scan.jpg'
    padx = 5
    pady = 5

    def __init__(self, model):
        self.model = model
        self.productFrame = None
        self.activeFrame = None
        self.inactiveFrame = None
        self.obsoleteFrame = None
        self.scrollbarY = None

        width = self.model.db.config.getint('general', 'screen_width')
        width = None if width == -1 else width
        height = self.model.db.config.getint('general', 'screen_height')
        height = None if height == -1 else height
        super().__init__(width, height, helpers.Log())

    def populateRoot(self):
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
        self.populateActiveFrame()

        if self.inactiveFrame is None:
            self.inactiveFrame = tkinter.Frame(self.productFrame.scrolledwindow, relief=tkinter.GROOVE)
        for w in self.inactiveFrame.winfo_children():
            w.destroy()
        self.populateInactiveFrame()

        if self.obsoleteFrame is None:
            self.obsoleteFrame = tkinter.Frame(self.productFrame.scrolledwindow, relief=tkinter.GROOVE)
        for w in self.obsoleteFrame.winfo_children():
            w.destroy()
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
        activeLabel = tkinter.Label(self.activeFrame, text='Active sheets')
        activeLabel.pack(side=tkinter.TOP, fill=tkinter.X, padx = self.padx, pady = self.pady)
        gui_components.ToolTip(activeLabel,
                ('These sheets should be available for customers to tag '
                '(physical printouts in the store) after accounting is done.'))

        self.__addCategoryFrame(self.activeFrame, 'New', 'newActive',
                ('These sheets were marked inactive last time, but '
                'they should not be according to products.csv\n'
                'Make sure they are available to customers.'),
                ('Deactivate', 'newInactive'),
                ('Replace', 'replace')
                ).config(background='tan1')

        self.__addCategoryFrame(self.activeFrame, 'Missing Scans', 'missingActive',
                ('These sheets should be active but have not been scanned.\n'
                'Either leave it for the next time (customers will be billed '
                'with next accounting),\n'
                'or cancel tagtrail_account, scan these sheets, run '
                'tagtrail_ocr with --individualScan option and '
                'tagtrail_sanitize before restarting tagtrail_account.'),
                ('Deactivate', 'newInactive'),
                ('Remove', 'remove')
                ).config(background='tan1')

        self.__addCategoryFrame(self.activeFrame, 'Unchanged', 'active',
                'These sheets are active and have been scanned. All good.',
                ('Deactivate', 'newInactive'),
                ('Replace', 'replace')
                ).config(background='green')

    def populateInactiveFrame(self):
        inactiveLabel = tkinter.Label(self.inactiveFrame, text='Inactive sheets')
        inactiveLabel.pack(side=tkinter.TOP, fill=tkinter.X, padx = self.padx, pady = self.pady)
        gui_components.ToolTip(inactiveLabel,
                ('These sheets should be kept somewhere out of customers'
                ' reach, ready for reuse when new stock arrives.'))

        self.__addCategoryFrame(self.inactiveFrame, 'New', 'newInactive',
                ('These sheets were scanned but became inactive (product sold '
                'out).\n'
                'Remove them from the store and keep them somewhere for later '
                'reuse.'),
                ('Activate', 'newActive'),
                ('Remove', 'remove')
                ).config(background='tan1')

        self.__addCategoryFrame(self.inactiveFrame, 'Unchanged', 'inactive',
                ('These sheets were already inactive after last accounting, '
                'just keep them for later reuse.'),
                ('Activate', 'newActive'),
                ('Remove', 'remove')
                ).config(background='green')

    def populateObsoleteFrame(self):
        obsoleteLabel = tkinter.Label(self.obsoleteFrame, text='Obsolete sheets')
        obsoleteLabel.pack(side=tkinter.TOP, fill=tkinter.X, padx = self.padx, pady = self.pady)
        gui_components.ToolTip(obsoleteLabel,
                ('These sheets are full and should be removed and destroyed '
                'or archived.'))

        self.__addCategoryFrame(self.obsoleteFrame, 'To be replaced', 'replace',
                ('You selected these sheets to be replaced (E.g. because they '
                'are damaged).\n'
                'Remove them from the store and replace them with a new '
                'copy from 1_emptySheets/products/.'),
                ('Activate', 'newActive'),
                ('Deactivate', 'newInactive')
                ).config(background='tan1')

        self.__addCategoryFrame(self.obsoleteFrame, 'To be removed', 'remove',
                ('These sheets should be removed and thrown away '
                'or archived.'),
                ('Activate', 'newActive'),
                ('Deactivate', 'newInactive')
                ).config(background='tan1')

    def __addCategoryFrame(self, parent, title, category, tooltip,
            button1 = None, button2 = None):
        """
        Add a frame with all sheets of one category, plus optional buttons for
        the user to change the category of each sheet.

        :param parent: parent widget
        :type parent: tkinter widget
        :param title: title of the frame
        :type title: str
        :param category: category identifier
        :type category: str
        :param tooltip: tooltip describing the category and necessary actions
        to be taken for sheets in this category to the user
        :type tooltip: str
        :param button1: (text, category) to initialize a button which sets the
        corresponding sheet to another category
        :type button1: pair (str, str)
        :param button2: (text, category) to initialize a button which sets the
        corresponding sheet to another category
        :type button2: pair (str, str)
        :return: created frame
        :rtype: tkinter.Frame
        """
        frame = tkinter.Frame(parent)
        tkinter.Label(frame, text=title).grid(row=0, column=0)
        rowIdx = 0
        for sheet in self.model.accountedSheets:
            if sheet.category != category:
                continue
            rowIdx += 1
            tkinter.Label(frame, text=sheet.filename).grid(
                    row=rowIdx, column=0, padx = self.padx, pady = self.pady)
            if button1 is not None:
                b = tkinter.Button(frame, text=button1[0])
                command = functools.partial(self.__setSheetCategory, sheet,
                        button1[1])
                b.bind('<Button-1>', command)
                b.bind('<Return>', command)
                b.grid(row=rowIdx, column=1)
            if button2 is not None:
                b = tkinter.Button(frame, text=button2[0])
                command = functools.partial(self.__setSheetCategory, sheet,
                        button2[1])
                b.bind('<Button-1>', command)
                b.bind('<Return>', command)
                b.grid(row=rowIdx, column=2, padx = self.padx, pady = self.pady)

        frame.pack(side=tkinter.TOP, fill=tkinter.X, padx = self.padx, pady = self.pady)
        frame.config(relief=tkinter.GROOVE, bd=2)
        gui_components.ToolTip(frame, tooltip)
        frame.update()
        return frame

    def __setSheetCategory(self, sheet, category, event):
        """
        Set the category of sheet, to be passed to buttons

        :param sheet: sheet
        :type sheet: :class:`ProductSheet`
        :param category: category, one of ('newActive', 'missingActive', 'active',
        'newInactive', 'inactive', 'replace', 'remove')
        :type category: str
        :param event: tkinter event
        """
        if category not in ['newActive', 'missingActive', 'active',
                'newInactive', 'inactive', 'replace', 'remove']:
            raise ValueError(f'invalid category: {category}')
        sheet.category = category
        self.populateRoot()

    def saveAndQuit(self, event = None):
        try:
            self.model.save()
        finally:
            self.root.quit()

    def cancelAndQuit(self, event = None):
        self.root.quit()

class Model():
    """
    Model class exposing all functionality needed to account sanitized product
    sheets, create export files for GnuCash and bills for all members.

    :param rootDir: root directory for the accounting
    :type rootDir: str
    :param renamedRootDir: new name of root directory after accounting is done
    :type renamedRootDir: str
    :param nextRootDir: root directory to be prepared for the next accounting
    :type nextRootDir: str
    :param accountingDate: date of the accounting
    :type accountingDate: :class: `datetime.date`
    :param updateCo2Statistics: `True` if new Co2 values should be queried from
        eaternity
    :param updateCo2Statistics: bool
    :param keyringPassword: password to open the keyring. needed to
        update Co2 statistics. If it is None, the user will be asked to enter
        it interactively.
    :type keyringPassword: str
    :param log: logger to write messages to
    :type log: class: `helpers.Log`
    """
    def __init__(self, rootDir, renamedRootDir,
            nextRootDir, accountingDate, updateCo2Statistics,
            keyringPassword = None, log = helpers.Log(helpers.Log.LEVEL_INFO)):
        self.rootDir = rootDir
        self.renamedRootDir = renamedRootDir
        self.nextRootDir = nextRootDir
        self.accountingDate = accountingDate
        self.updateCo2Statistics = updateCo2Statistics
        self.keyringPassword = keyringPassword
        self.log = log
        self.db = database.Database(f'{rootDir}0_input/')
        if (self.db.products.inventoryQuantityDate is not None and
                self.db.products.inventoryQuantityDate != accountingDate):
            raise ValueError(
                'Inventory (when you check the actually remaining products) '
                'must be done on the same day as the accounting (when you '
                'scan the product sheets, download the payments)\n'
                'inventoryQuantityDate != accountingDate: ('
                f'{self.db.products.inventoryQuantityDate} != {accountingDate}'
                ')\n'
                'To do a valid accounting, either redo the inventory or '
                'the accounting.')

    def loadAccountData(self):
        """
        Load tags and input transactions, create bills, purchase and inventory difference
        transactions and categorize accounted sheets to be able to show the user what
        to do with each sheet and to prepare the next accounting.
        """
        if self.updateCo2Statistics:
            apiKey = None
            if self.keyringPassword is not None:
                keyring = helpers.Keyring(self.db.config.get('general',
                    'password_file_path'), self.keyringPassword)
                apiKey = keyring.get_password('eaternity', 'apiKey')
            api = eaternity.EaternityApi(self.db.config, apiKey)
            for product in self.db.products.values():
                try:
                    gCo2e = api.co2Value(product)
                    if product.gCo2e != gCo2e:
                        self.log.info(f'Updated gCo2e from {product.gCo2e} '
                                +f'to {gCo2e} for {product.id}')
                        product.gCo2e = gCo2e
                    else:
                        self.log.debug(f'gCo2e for {product.id} = {gCo2e}')

                except ValueError:
                    self.log.info(f'Failed to retrieve gCo2e for {product.id}')

        tagCollector = TagCollector(
                self.rootDir+'0_input/sheets/',
                self.rootDir+'2_taggedProductSheets/',
                self.accountingDate,
                self.db, self.log)

        self.db.products.expectedQuantityDate = self.accountingDate
        for productId, product in self.db.products.items():
            product.soldQuantity = tagCollector.numNewTags(productId,
                    list(self.db.members.keys()))

        self.correctionTransactions = self.db.readCsv(
                self.rootDir+'0_input/correctionTransactions.csv',
                database.CorrectionTransactionDict)
        unknownMembers = [memberId for memberId in self.correctionTransactions
                if memberId not in self.db.members.keys()]

        if unknownMembers:
            raise ValueError('invalid memberIds in '
                    f'correctionTransactions: {unknownMembers}')
        self.paymentTransactions = self.loadPaymentTransactions()
        self.bills = self.createBills(tagCollector)
        self.inventoryDifferenceTransactions = self.createInventoryDifferenceTransactions()
        self.purchaseTransactions = self.createPurchaseTransactions()
        self.accounts = database.MemberAccountDict(self.db.config,
                **{m.id: database.MemberAccount(m.id) for m in self.db.members.values()})
        self.accountedSheets = self.categorizeAccountedSheets(tagCollector)

    def categorizeAccountedSheets(self, tagCollector):
        """
        Sort active/inactive input sheets and scanned sheets into various
        categories to present to the user and prepare the next accounting.

        :param tagCollector: initialized TagCollector with loaded and checked sheets
        :type tagCollector: :class:`TagCollector`
        :return: alphabetically (by filename) sorted list of all accounted sheets, where each sheet has one of the
            following categories set: ('newActive', 'missingActive', 'active',
            'newInactive', 'inactive', 'replace', 'remove')
        :rtype: list of :class:`ProductSheet`
        """
        accountedSheets = []

        fullSheets = []
        for sheet in tagCollector.scannedSheets.values():
            if sheet.isFull():
                sheet.category = 'remove'
                accountedSheets.append(sheet)
                fullSheets.append(sheet.filename)

        for (pId, pNum), sheet in tagCollector.inactiveInputSheets.items():
            if sheet.filename in fullSheets:
                continue
            if self.db.products[pId].expectedQuantity <= 0:
                if (pId, pNum) in tagCollector.scannedSheets:
                    sheet.category = 'newInactive'
                else:
                    sheet.category = 'inactive'
                accountedSheets.append(sheet)
            else:
                sheet.category = 'newActive'
                accountedSheets.append(sheet)

        for (pId, pNum), sheet in tagCollector.activeInputSheets.items():
            if sheet.filename in fullSheets:
                continue
            if (pId, pNum) not in tagCollector.scannedSheets:
                sheet.category = 'missingActive'
                accountedSheets.append(sheet)
            elif self.db.products[pId].expectedQuantity <= 0:
                sheet.category = 'newInactive'
                accountedSheets.append(sheet)
            else:
                sheet.category = 'active'
                accountedSheets.append(sheet)

        accountedSheetFilenames = [s.filename for s in accountedSheets]
        if len(accountedSheetFilenames) != len(set(accountedSheetFilenames)):
            raise AssertionError('Sheet assigned to several categories:\n'
                f'{accountedSheetFilenames}')

        return sorted(accountedSheets, key=lambda sheet: sheet.filename)

    def loadPaymentTransactions(self):
        toDate = self.accountingDate-datetime.timedelta(days=1)
        unprocessedTransactionsPath = self.rootDir + \
                '5_output/unprocessed_Transactions_' + \
                helpers.DateUtility.strftime(self.previousAccountingDate) + '_' + \
                helpers.DateUtility.strftime(toDate) + '.csv'
        paymentTransactionsPath = self.rootDir+'4_gnucash/transactions.csv'

        if not os.path.isfile(unprocessedTransactionsPath):
            raise Exception(
                f"{unprocessedTransactionsPath} does not exist.\n" + \
                "Run tagtrail_bankimport before tagtrail_account!")
        if not os.path.isfile(paymentTransactionsPath):
            raise Exception(
                f"{paymentTransactionsPath} does not exist.\n" + \
                "Run tagtrail_bankimport before tagtrail_account!")

        unprocessedPayments = [t.notificationText for t in
                self.db.readCsv(unprocessedTransactionsPath,
                    database.PostfinanceTransactionList)
                 if not t.creditAmount is None]
        if unprocessedPayments != []:
            messagebox.showwarning('Unprocessed payments exist',
                'Following payments will not be documented for our members:\n\n'
                + '\n\n'.join(unprocessedPayments) + '\n\n'
                + 'Run tagtrail_bankimport again if you want to correct this.')

        return self.db.readCsv(paymentTransactionsPath,
                database.GnucashTransactionList)

    def createBills(self, tagCollector):
        bills = {}
        for member in self.db.members.values():
            bill = database.Bill(self.db.config,
                    member.id,
                    self.db.members.accountingDate,
                    self.accountingDate,
                    member.balance,
                    sum([transaction.amount for transaction in
                        self.paymentTransactions
                        if transaction.sourceAccount == member.id]),
                    self.correctionTransactions[member.id].amount if member.id in self.correctionTransactions else 0,
                    self.correctionTransactions[member.id].justification if member.id in self.correctionTransactions else '')
            for productId in tagCollector.newTagsPerProduct.keys():
                numTags = tagCollector.numNewTags(productId, [member.id])
                if numTags != 0:
                    taggedGrossSalesPrice = tagCollector.taggedGrossSalesPrice(productId)
                    assert(taggedGrossSalesPrice is not None)
                    position = database.BillPosition(productId,
                            self.db.products[productId].description,
                            numTags,
                            self.db.products[productId].purchasePrice,
                            taggedGrossSalesPrice,
                            self.db.products[productId].gCo2e)
                    bill[position.id] = position
            bills[member.id] = bill
        return bills

    def createInventoryDifferenceTransactions(self):
        transactions = database.GnucashTransactionList(self.db.config)
        if self.db.products.inventoryQuantityDate is None:
            return transactions

        inventoryDifference = self.db.config.get('tagtrail_account',
                'inventory_difference')
        inventoryDifferenceAccount = self.db.config.get('tagtrail_account',
                'inventory_difference_account')
        self.log.info('\nDifferences between inventory and expected quantities:\n')
        for product in self.db.products.values():
            if product.inventoryQuantity is None:
                continue

            quantityDifference = product.expectedQuantity - product.inventoryQuantity
            purchasePriceDifference = quantityDifference * product.purchasePrice
            grossSalesPriceDifference = quantityDifference * product.grossSalesPrice()

            if quantityDifference != 0:
                quantityDifferenceMsg = (f'{product.id}: expected = {product.expectedQuantity}, ' +
                        f'inventory = {product.inventoryQuantity}, ' +
                        f'difference = {quantityDifference}')
                self.log.info(quantityDifferenceMsg)
                transactions.append(database.GnucashTransaction(
                    f'{product.id}: {inventoryDifference} accounted on {self.accountingDate}',
                    purchasePriceDifference,
                    self.db.config.get('tagtrail_account',
                        'merchandise_value_account'),
                    inventoryDifferenceAccount,
                    self.accountingDate
                    ))
                transactions.append(database.GnucashTransaction(
                    f'{product.id}: {inventoryDifference} accounted on {self.accountingDate}',
                    grossSalesPriceDifference - purchasePriceDifference,
                    self.db.config.get('tagtrail_account', 'margin_account'),
                    inventoryDifferenceAccount,
                    self.accountingDate
                    ))
        return transactions

    def createPurchaseTransactions(self):
        merchandiseValue = self.db.config.get('tagtrail_account',
                'merchandise_value')
        merchandiseValueAccount = self.db.config.get('tagtrail_account',
                'merchandise_value_account')
        margin = self.db.config.get('tagtrail_account', 'margin')
        marginAccount = self.db.config.get('tagtrail_account', 'margin_account')
        return database.GnucashTransactionList(
                self.db.config,
                ([database.GnucashTransaction(
                    f'{merchandiseValue} accounted on {self.accountingDate}',
                    bill.totalPurchasePrice(),
                    merchandiseValueAccount,
                    bill.memberId,
                    self.accountingDate) for bill in self.bills.values()]
                +
                [database.GnucashTransaction(
                    f'{margin} accounted on {self.accountingDate}',
                    bill.totalGrossSalesPrice()-bill.totalPurchasePrice(),
                    marginAccount,
                    bill.memberId,
                    self.accountingDate) for bill in self.bills.values()])
                )

    @property
    def previousAccountingDate(self):
        return self.db.members.accountingDate

    def save(self):
        self.checkConsistency()
        self.writeBills()
        self.writeGnuCashFiles()
        self.writeAccountedProductSheets()
        if self.renamedRootDir != self.rootDir:
            shutil.move(self.rootDir, self.renamedRootDir)
        self.prepareNextAccounting()

    def checkConsistency(self):
        """
        Do some basic consistency checks to insure accounting quality
        """
        # value sold per product should be equivalent to billed sum
        for productId, product in self.db.products.items():
            numTagsBilled = 0
            for bill in self.bills.values():
                for billPosition in bill.values():
                    if billPosition.id == productId:
                        numTagsBilled += billPosition.numTags
            expectedTotal = product.soldQuantity * product.grossSalesPrice()
            if numTagsBilled != product.soldQuantity:
                raise ValueError(f'number of tags billed for {productId} '
                        f'differs from expected: '
                        '{numTagsBilled} != {product.soldQuantity}\n'
                        'This is a serious bug, please file a report at '
                        'https://github.com/greuters/tagtrail.')

    def writeBills(self):
        destPath = f'{self.rootDir}3_bills/to_be_sent/'
        helpers.recreateDir(destPath, self.log)
        helpers.recreateDir(f'{self.rootDir}3_bills/already_sent/', self.log)
        for member in self.db.members.values():
            self.db.writeCsv(destPath+member.id+'.csv',
                    self.bills[member.id])

    def writeGnuCashFiles(self):
        destPath = f'{self.rootDir}/4_gnucash/'
        self.db.writeCsv(f'{destPath}accounts.csv', self.accounts)
        transactions = database.GnucashTransactionList(
                self.db.config,
                itertools.chain(self.purchaseTransactions,
                self.inventoryDifferenceTransactions,
                self.paymentTransactions))

        self.db.writeCsv(f'{destPath}transactions.csv',
                transactions)

    def writeAccountedProductSheets(self):
        helpers.recreateDir(f'{self.rootDir}5_output/sheets/active/', self.log)
        helpers.recreateDir(f'{self.rootDir}5_output/sheets/inactive/', self.log)
        helpers.recreateDir(f'{self.rootDir}5_output/sheets/obsolete/removed/', self.log)
        helpers.recreateDir(f'{self.rootDir}5_output/sheets/obsolete/replaced/', self.log)
        if [s for s in self.accountedSheets if s.category == 'replace'] != []:
            helpers.recreateDir(f'{self.rootDir}1_emptySheets/', self.log)
        helpers.recreateDir(f'{self.rootDir}5_output/sheets/obsolete/replaced/', self.log)
        for sheet in self.accountedSheets:
            outputPath = f'{self.rootDir}5_output/sheets/'
            if sheet.category in ['active', 'newActive', 'missingActive']:
                outputPath += 'active/'
            elif sheet.category in ['newInactive', 'inactive']:
                outputPath += 'inactive/'
            elif sheet.category == 'remove':
                outputPath += 'obsolete/removed/'
            elif sheet.category == 'replace':
                # generate replacement sheet
                emptySheet = ProductSheet()
                emptySheet.name = sheet.name
                emptySheet.amountAndUnit = sheet.amountAndUnit
                emptySheet.grossSalesPrice = sheet.grossSalesPrice
                emptySheet.sheetNumber = sheet.sheetNumber
                emptySheetPath = (self.rootDir +
                        '1_emptySheets/' + sheet.filename + '.jpg')
                if cv.imwrite(emptySheetPath, emptySheet.createImg()) is True:
                    self.log.info(f'generated sheet {emptySheetPath}')
                else:
                    raise ValueError(f'failed to generate sheet {emptySheetPath}')
                emptySheet.store(outputPath + 'active/')
                outputPath += 'obsolete/replaced/'
            else:
                assert(False)

            # Available sources of a sheet might be non-intuitive, as users
            # can assign virtually any category to a sheet.
            #
            # As an example, a newActive sheet usually has only an inactive
            # input file and no scan. However, it could also have a scanned and
            # an active input file if the user assigned an active file to be
            # inactive and then activated it again.
            #
            # What is guaranteed is that scanned sheets always take precedence
            # over input sheets and either an active or an inactive input
            # sheet must exist of any product sheet.
            scanInputPath = f'{self.rootDir}/2_taggedProductSheets/'
            activeInputPath = f'{self.rootDir}/0_input/sheets/active/'
            inactiveInputPath = f'{self.rootDir}/0_input/sheets/inactive/'
            if os.path.exists(f'{scanInputPath}{sheet.filename}'):
                shutil.copy(f'{scanInputPath}{sheet.filename}',
                        f'{outputPath}{sheet.filename}')
            elif os.path.exists(f'{activeInputPath}{sheet.filename}'):
                shutil.copy(f'{activeInputPath}{sheet.filename}',
                        f'{outputPath}{sheet.filename}')
            elif os.path.exists(f'{inactiveInputPath}{sheet.filename}'):
                shutil.copy(f'{inactiveInputPath}{sheet.filename}',
                        f'{outputPath}{sheet.filename}')
            else:
                raise AssertionError(
                        f'No file found for {sheet.filename} ')

    def prepareNextAccounting(self):
        helpers.recreateDir(self.nextRootDir, self.log)
        helpers.recreateDir(f'{self.nextRootDir}0_input', self.log)
        helpers.recreateDir(f'{self.nextRootDir}0_input/sheets', self.log)
        helpers.recreateDir(f'{self.nextRootDir}0_input/scans', self.log)
        self.writeMemberCSV()
        self.writeProductsCSVs()
        self.copyAccountedSheets()
        self.db.writeCsv(f'{self.nextRootDir}0_input/correctionTransactions.csv',
                database.CorrectionTransactionDict(self.db.config))
        shutil.copytree(f'{self.renamedRootDir}0_input/templates',
                f'{self.nextRootDir}0_input/templates')

    def writeMemberCSV(self):
        newMembers = copy.deepcopy(self.db.members)
        newMembers.accountingDate = self.accountingDate
        for m in newMembers.values():
            m.balance = self.bills[m.id].currentBalance
        self.db.writeCsv(f'{self.renamedRootDir}5_output/members.tsv',
                newMembers)
        self.db.writeCsv(f'{self.nextRootDir}0_input/members.tsv',
                newMembers)

    def writeProductsCSVs(self):
        self.db.writeCsv(f'{self.renamedRootDir}5_output/products.csv',
                self.db.products)
        self.db.writeCsv(f'{self.nextRootDir}0_input/products.csv',
                self.db.products.copyForNext(self.accountingDate, False, True))

    def copyAccountedSheets(self):
        shutil.copytree(f'{self.renamedRootDir}5_output/sheets/active',
                f'{self.nextRootDir}0_input/sheets/active')
        shutil.copytree(f'{self.renamedRootDir}5_output/sheets/inactive',
                f'{self.nextRootDir}0_input/sheets/inactive')


def main(accountingDir, renamedAccountingDir, accountingDate,
        nextAccountingDir, updateCo2Statistics):
    newDir = renamedAccountingDir.format(accountingDate = accountingDate)
    if newDir == nextAccountingDir:
        raise ValueError(f'nextAccountingDir must not be named {newDir}')
    model = Model(accountingDir, newDir, nextAccountingDir, accountingDate,
            updateCo2Statistics)
    model.loadAccountData()
    GUI(model)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Load payments and tagged product sheets to create a ' + \
            'bill for each member, provide transaction files ready to be ' + \
            'imported to GnuCash and prepare for the next accounting.')
    parser.add_argument('accountingDir',
            help='Top-level tagtrail directory to process, usually data/next/')
    parser.add_argument('--accountingDate',
            dest='accountingDate',
            type=helpers.DateUtility.strptime,
            default=helpers.DateUtility.todayStr(),
            help="Date of the new accounting, fmt='YYYY-mm-dd'",
            )
    parser.add_argument('--renamedAccountingDir',
            dest='renamedAccountingDir',
            default='data/account_{accountingDate}/',
            help="New name to rename accountingDir to. {accountingDate} " + \
                 "will be replaced by the value of the 'accountingDate' argument.")
    parser.add_argument('--nextAccountingDir',
            dest='nextAccountingDir',
            default='data/next/',
            help='Name of the top-level tagtrail directory to be created for the next accounting.')
    parser.add_argument('--updateCo2Statistics',
            action='store_true',
            default=False,
            help='Retrieve new gCo2e statistics from eaternity')

    args = parser.parse_args()
    main(args.accountingDir, args.renamedAccountingDir, args.accountingDate,
            args.nextAccountingDir, args.updateCo2Statistics)

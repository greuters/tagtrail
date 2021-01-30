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
.. module:: tagtrail_gen
   :platform: Linux
   :synopsis: A tool to generate ProductSheets and TagSheets ready to print.

.. moduleauthor:: Simon Greuter <simon.greuter@gmx.net>


"""
import argparse
import cv2 as cv
import functools
import slugify
import math
import tkinter
from tkinter import messagebox
import traceback
import os
import shutil

from . import helpers
from .database import Database
from .sheets import ProductSheet
from .helpers import Log
from . import gui_components

class Model():
    """
    Model class exposing all functionality needed to generate new ProductSheets
    """
    def __init__(self,
            rootDir,
            allowRemoval,
            genDate,
            renamedRootDir,
            nextDir,
            log = Log(Log.LEVEL_INFO)):
        self.rootDir = rootDir
        self.allowRemoval = allowRemoval
        self.genDate = genDate
        self.renamedRootDir = renamedRootDir
        self.nextDir = nextDir
        self.log = log
        self.db = Database(f'{rootDir}0_input/')
        self.sheets = []

        if self.db.products.inventoryQuantityDate is not None:
            raise ValueError(f'inventoryQuantityDate: {inventoryQuantityDate} '
                    'is not None\n'
                    'To do an inventory, run tagtrail_account - if you also '
                    'want to add new products, run tagtrail_gen afterwards on '
                    'the new next/ directory')

    @property
    def activeSheetsToBePrinted(self):
        """
        New product sheets to be printed (always active first)
        """
        return set([sheet for sheet in self.sheets
            if sheet.previousState == None and sheet.newState == 'active'])

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

    def initializeSheets(self):
        """
        Load existing active/inactive sheets and generate new ones
        where necessary to accomodate all product units in the salesmix.
        Remove sheets of products that are not in the database any more.

        Each sheet is assigned a previousState and a newState to be able to
        show the user what to do with each sheet and to prepare the next
        accounting.
        """
        self.sheets = []

        # remove sheets of products removed from database
        for filename in os.listdir(f'{self.rootDir}0_input/sheets/active/'):
            if ProductSheet.productId_from_filename(filename) \
                    not in self.db.products:
                sheet = ProductSheet(Log(Log.LEVEL_ERROR))
                sheet.load(f'{self.rootDir}0_input/sheets/active/{filename}')
                sheet.previousState = 'active'
                if self.allowRemoval:
                    sheet.newState = 'obsolete'
                    self.log.info(f'removing {filename} - product removed from database')
                else:
                    sheet.newState = 'active'
                self.sheets.append(sheet)

        for filename in os.listdir(f'{self.rootDir}0_input/sheets/inactive/'):
            if ProductSheet.productId_from_filename(filename) \
                    not in self.db.products:
                sheet = ProductSheet(Log(Log.LEVEL_ERROR))
                sheet.load(f'{self.rootDir}0_input/sheets/inactive/{filename}')
                sheet.previousState = 'inactive'
                if self.allowRemoval:
                    sheet.newState = 'obsolete'
                    self.log.info(f'removing {filename} - product removed from database')
                else:
                    sheet.newState = 'inactive'
                self.sheets.append(sheet)

        for productId, product in self.db.products.items():
            activeInputSheets = self.product_sheets_in_dir(productId,
                    f'{self.rootDir}0_input/sheets/active/')
            inactiveInputSheets = self.product_sheets_in_dir(productId,
                    f'{self.rootDir}0_input/sheets/inactive/')
            assert(product.inventoryQuantity is None)
            if product.expectedQuantity <= 0:
                # product out of stock but expected to be bought again
                if self.allowRemoval:
                    self.log.info(f'{product.id} out of stock - deactivating sheets')
                for s in activeInputSheets:
                    s.previousState = 'active'
                    if self.allowRemoval:
                        s.newState = 'inactive'
                    else:
                        s.newState = 'active'
                for s in inactiveInputSheets:
                    s.previousState = 'inactive'
                    s.newState = 'inactive'
            elif self.productNeedsGeneration(product,
                    activeInputSheets + inactiveInputSheets):
                # product changed - replace all sheets
                if not self.allowRemoval and (activeInputSheets != [] or
                        inactiveInputSheets != []):
                    raise ValueError(
                            f'Unable to replace sheets for {productId}\n'
                            'Run tagtrail_gen with --allowRemoval option '
                            'if you are sure no new tags have been added since '
                            'last accounting. If not, do an accounting before '
                            'adding new products.')

                for s in activeInputSheets:
                    s.previousState = 'active'
                    s.newState = 'obsolete'
                for s in inactiveInputSheets:
                    s.previousState = 'inactive'
                    s.newState = 'obsolete'
                numSheetsNeeded = math.ceil(product.expectedQuantity /
                        ProductSheet.maxQuantity())
                maxNumSheets = self.db.config.getint('tagtrail_gen',
                        'max_num_sheets_per_product')
                if numSheetsNeeded > maxNumSheets:
                    raise ValueError(f'Quantity of {productId} is too high, '
                            f'would need {numSheetsNeeded}, '
                            f'max {maxNumSheets} are allowed')
                # one based, as this goes out to customers
                for sheetNumber in range(1, numSheetsNeeded+1):
                    newSheet = self.generateProductSheet(product, sheetNumber)
                    newSheet.previousState = None
                    newSheet.newState = 'active'
                    self.sheets.append(newSheet)
            else:
                self.activateAndReplaceIndividualSheets(product, activeInputSheets,
                        inactiveInputSheets)

            self.sheets += activeInputSheets
            self.sheets += inactiveInputSheets
            self.sheets = sorted(self.sheets, key=lambda sheet: sheet.filename)

    def productNeedsGeneration(self, product, inputSheets):
        """
        Has `product` changed in a way that all sheets need to be regenerated?

        This is the case if at least one of the following criterias is true:
        * no previous sheets exist
        * amount or unit where changed compared to existing product sheets
        * price changed more than `max_neglectable_price_change_percentage`
        (check config/tagtrail.cfg) compared to existing product sheets
        * existing sheets don't provide enough room for tagging the
        product.expectedQuantity and the price changed (even a little)

        :param product: product to check
        :type product: :class:`database.Product`
        :param inputSheets: list of all existing sheets of the product
        :type inputSheets: list of :class: `sheets.ProductSheet`
        :return: True if sheets need to be regenerated
        :rtype: bool
        """
        if inputSheets == []:
            self.log.info(
                    f'regenerate sheets of {product.id}: no previous sheets exist')
            return True

        assert(len(set([s.name for s in inputSheets])) == 1)
        assert(len(set([s.amountAndUnit for s in inputSheets])) == 1)
        assert(len(set([s.grossSalesPrice for s in inputSheets])) == 1)
        inputSheet = inputSheets[0]

        if product.amountAndUnit.upper() != inputSheet.amountAndUnit.upper():
            self.log.info(
                    f'regenerate sheets of {product.id}: amount/unit changed '
                    f'from {inputSheet.amountAndUnit} to '
                    f'{product.amountAndUnit}')
            return True

        priceChangeThreshold = self.db.config.getint('tagtrail_gen',
                'max_neglectable_price_change_percentage')
        if (abs(product.grossSalesPrice()-inputSheet.grossSalesPrice) /
                inputSheet.grossSalesPrice > priceChangeThreshold / 100):
            self.log.info(
                    f'regenerate sheets of {product.id}: price changed more '
                    f'than {priceChangeThreshold}%, from '
                    f'{inputSheet.grossSalesPrice} to '
                    f'{product.grossSalesPrice()}')
            return True

        numFreeTags = 0
        for s in inputSheets:
            numFreeTags += len(s.emptyDataBoxes())
        if (product.grossSalesPrice() != inputSheet.grossSalesPrice and
                numFreeTags < product.expectedQuantity):
            self.log.info(
                    f'regenerate sheets of {product.id}: '
                    'not enough free tags and price changed '
                    f'from {inputSheet.grossSalesPrice} to '
                    f'{product.grossSalesPrice()}')
            return True

        return False

    def activateAndReplaceIndividualSheets(self, product, activeInputSheets,
                        inactiveInputSheets):
        """
        Activate inactive sheets and add new sheets to print until enough room
        is available to accomodate the expected quantity

        If self.allowRemoval == True, full sheets are removed, active ones can
        be deactivated and existing sheets replaced where necessary.

        :param product: product to consider
        :type product: :class: `database.Product`
        :param activeInputSheets: list of active sheets of product in 0_input
        :type activeInputSheets: list of :class: `sheets.ProductSheet`
        :param activeInputSheets: list of inactive sheets of product in 0_input
        :type activeInputSheets: list of :class: `sheets.ProductSheet`
        """
        # check if expected quantity would be feasible if all sheets
        # are replaced
        numSheetsNeeded = math.ceil(product.expectedQuantity /
                ProductSheet.maxQuantity())
        maxNumSheets = self.db.config.getint('tagtrail_gen',
                'max_num_sheets_per_product')
        self.log.debug(f'activateAndReplaceIndividualSheets for {product.id}')
        self.log.debug(f'numSheetsNeeded for {product.id} = {numSheetsNeeded}')
        if maxNumSheets < numSheetsNeeded:
            raise ValueError(f'Quantity of {product.id} is too high, '
                    f'would need {numSheetsNeeded}, max '
                    f'{maxNumSheets} are allowed')

        # first, use active sheets without replacement
        numFreeTags = 0
        for s in sorted(activeInputSheets,
                key = lambda s: len(s.emptyDataBoxes()), reverse=True):
            if s.isFull() and self.allowRemoval:
                s.previousState = 'active'
                s.newState = 'obsolete'
            elif (numFreeTags < product.expectedQuantity
                    or not self.allowRemoval):
                s.previousState = 'active'
                s.newState = 'active'
                numFreeTags += len(s.emptyDataBoxes())
            else:
                s.previousState = 'active'
                s.newState = 'inactive'

        # activate inactive sheets if necessary
        for s in sorted(inactiveInputSheets,
                key = lambda s: len(s.emptyDataBoxes()), reverse=True):
            if s.isFull() and self.allowRemoval:
                s.previousState = 'inactive'
                s.newState = 'obsolete'
            elif numFreeTags < product.expectedQuantity:
                s.previousState = 'inactive'
                s.newState = 'active'
                numFreeTags += len(s.emptyDataBoxes())
            else:
                s.previousState = 'inactive'
                s.newState = 'inactive'

        # generate new sheets until we have enough free tags if necessary
        if numFreeTags >= product.expectedQuantity:
            return

        activeInputSheetNumbers = [self.parseSheetNumber(s.sheetNumber)
                for s in activeInputSheets]
        inactiveInputSheetNumbers = [self.parseSheetNumber(s.sheetNumber)
                for s in inactiveInputSheets]
        newSheetNumbers = [n for n in range(1, maxNumSheets+1)
                if n not in
                activeInputSheetNumbers + inactiveInputSheetNumbers]
        if (numFreeTags + len(newSheetNumbers)*ProductSheet.maxQuantity() <
                product.expectedQuantity
                and not self.allowRemoval):
            raise ValueError( 'Unable to replace sheets for '
                    f'{product.id}\n'
                    'Run tagtrail_gen with --allowRemoval option if '
                    'you are sure no new tags have been added since '
                    'last accounting. If not do an accounting before '
                    'adding new products.')

        sheetNumbersInReplacementOrder = newSheetNumbers
        if self.allowRemoval:
            sheetNumbersInReplacementOrder += [
                    self.parseSheetNumber(s.sheetNumber) for s in sorted(
                        activeInputSheets + inactiveInputSheets,
                        key = lambda s: len(s.emptyDataBoxes()))]

        self.log.debug(f'activeInputSheetNumbers: {activeInputSheetNumbers}')
        self.log.debug(f'inactiveInputSheetNumbers: {inactiveInputSheetNumbers}')
        self.log.debug(f'newSheetNumbers: {newSheetNumbers}')
        self.log.debug(f'sheetNumbersInReplacementOrder: {sheetNumbersInReplacementOrder}')

        for sheetNumber in sheetNumbersInReplacementOrder:
            if numFreeTags >= product.expectedQuantity:
                break

            if sheetNumber in (activeInputSheetNumbers):
                for s in activeInputSheets:
                    if (self.parseSheetNumber(s.sheetNumber) == sheetNumber):
                        s.previousState = 'active'
                        s.newState = 'obsolete'
                        numFreeTags -= len(s.emptyDataBoxes())

            if sheetNumber in (inactiveInputSheetNumbers):
                for s in inactiveInputSheets:
                    if (self.parseSheetNumber(s.sheetNumber) == sheetNumber):
                        s.previousState = 'inactive'
                        s.newState = 'obsolete'
                        numFreeTags -= len(s.emptyDataBoxes())

            newSheet = self.generateProductSheet(product, sheetNumber)
            newSheet.previousState = None
            newSheet.newState = 'active'
            self.log.info(f'generate empty sheet {newSheet.filename} '
                    'to create enough free tags')
            self.sheets.append(newSheet)
            numFreeTags += ProductSheet.maxQuantity()

        for s in activeInputSheets + inactiveInputSheets:
            assert(hasattr(s, 'previousState'))
            assert(hasattr(s, 'newState'))

    def product_sheets_in_dir(self, productId, inputDir):
        """
        Load all product sheets of a given product in a directory

        :param productId: id of the product to look for
        :type productId: str
        :param inputDir: directory to check
        :type inputDir: str
        :return: list of loaded product sheets
        :rtype: list of :class: `sheets.ProductSheet`
        """
        sheets = []
        for filename in self.product_sheet_filenames_in_dir(productId,
                inputDir):
                sheet = ProductSheet(Log(Log.LEVEL_ERROR))
                sheet.load(inputDir + filename)
                sheets.append(sheet)
        return sheets

    def product_sheet_filenames_in_dir(self, productId, inputDir):
        """
        Retrieve filenames of all sheets of a given product in a directory

        :param productId: id of the product to look for
        :type productId: str
        :param inputDir: directory to check
        :type inputDir: str
        :return: list of filenames
        :rtype: list of str
        """
        return [filename for filename in os.listdir(inputDir) if
                ProductSheet.productId_from_filename(filename) == productId]

    def generateProductSheet(self, product, sheetNumber):
        """
        Generate a new :class: `sheets.ProductSheet`

        :param product: the product to generate a sheet for
        :type product: :class: `database.Product`
        :param sheetNumber: number of the sheet
        :type sheetNumber: int
        :return: a new product sheet
        :rtype: :class: `sheets.ProductSheet`
        """
        sheet = ProductSheet(Log(Log.LEVEL_ERROR))
        sheet.name = product.description
        sheet.amountAndUnit = product.amountAndUnit
        sheet.grossSalesPrice = helpers.formatPrice(
                product.grossSalesPrice(),
                self.db.config.get('general', 'currency'))
        sheet.sheetNumber = self.db.config.get('tagtrail_gen',
                'sheet_number_string').format(sheetNumber=str(sheetNumber))
        return sheet

    def save(self):
        # make sure sheets are consistent
        prices = {} # productId -> price
        amountsAndUnits = {} # productId -> amountsAndUnits
        for sheet in (self.activeSheetsToBePrinted
                .union(self.activeSheetsFromActive)
                .union(self.activeSheetsFromInactive)
                .union(self.inactiveSheetsFromActive)
                .union(self.inactiveSheetsFromInactive)):
            if sheet.productId() not in prices:
                prices[sheet.productId()] = sheet.grossSalesPrice
            assert(prices[sheet.productId()] == sheet.grossSalesPrice)
            if sheet.productId() not in amountsAndUnits:
                amountsAndUnits[sheet.productId()] = sheet.amountAndUnit
            assert(amountsAndUnits[sheet.productId()] == sheet.amountAndUnit)

        # generate new sheets
        sheetDir = f'{self.rootDir}1_generatedSheets/'
        helpers.recreateDir(sheetDir)

        for sheet in self.activeSheetsToBePrinted:
            imgPath = f'{sheetDir}{sheet.productId()}_{sheet.sheetNumber}.jpg'
            if cv.imwrite(imgPath, sheet.createImg()) is True:
                self.log.info(f'generated sheet {imgPath}')
            else:
                raise ValueError(f'failed to generate sheet {imgPath}')

        # store output
        outputDir = f'{self.rootDir}5_output/'
        sheetsOutputDir = f'{outputDir}sheets/'
        activeSheetsOutputDir = f'{sheetsOutputDir}active/'
        inactiveSheetsOutputDir = f'{sheetsOutputDir}inactive/'
        removedSheetsOutputDir = f'{sheetsOutputDir}obsolete/removed/'
        replacedSheetsOutputDir = f'{sheetsOutputDir}obsolete/replaced/'
        helpers.recreateDir(outputDir)
        helpers.recreateDir(sheetsOutputDir)
        helpers.recreateDir(activeSheetsOutputDir)
        helpers.recreateDir(inactiveSheetsOutputDir)
        helpers.recreateDir(f'{sheetsOutputDir}obsolete/')
        helpers.recreateDir(removedSheetsOutputDir)
        helpers.recreateDir(replacedSheetsOutputDir)
        priceChangeThreshold = self.db.config.getint('tagtrail_gen',
                'max_neglectable_price_change_percentage') / 100
        for sheet in (self.activeSheetsToBePrinted
                .union(self.activeSheetsFromActive)
                .union(self.activeSheetsFromInactive)):
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

        self.db.writeCsv(f'{self.rootDir}5_output/products.csv',
                self.db.products)
        shutil.copy(f'{self.rootDir}0_input/members.tsv',
                f'{self.rootDir}5_output/members.tsv')

        if self.renamedRootDir != self.rootDir:
            shutil.move(self.rootDir, self.renamedRootDir)

        # initialize next
        helpers.recreateDir(self.nextDir)
        shutil.copytree(f'{self.renamedRootDir}0_input',
                f'{self.nextDir}0_input')
        helpers.recreateDir(f'{self.nextDir}0_input/sheets', self.log)
        shutil.copytree(f'{self.renamedRootDir}5_output/sheets/active',
                f'{self.nextDir}0_input/sheets/active')
        shutil.copytree(f'{self.renamedRootDir}5_output/sheets/inactive',
                f'{self.nextDir}0_input/sheets/inactive')
        self.db.writeCsv(f'{self.nextDir}0_input/products.csv',
                self.db.products.copyForNext(self.genDate, True, False))

    def parseSheetNumber(self, sheetNumberStr):
        """
        Parse the sheet number from a formatted sheet number string

        :param sheetNumberStr: sheet number string in tagtrail.cfg
            `sheet_number_string` format
        :type sheetNumberStr: str
        :return: parsed number
        :rtype: int
        """
        # TODO: save actual sheet number instead of only string version on the
        # sheet
        digits = ''.join([s for s in sheetNumberStr.split() if s.isdigit()])
        assert(self.db.config.get('tagtrail_gen', 'sheet_number_string')
                .format(sheetNumber=digits).upper() == sheetNumberStr.upper())
        return int(digits)


class GUI(gui_components.BaseGUI):
    padx = 5
    pady = 5
    scanPostfix = '_normalized_scan.jpg'

    def __init__(self,
            model,
            log = Log(Log.LEVEL_INFO)):
        self.model = model
        self.log = log

        self.productFrame = None
        self.activeFrame = None
        self.inactiveFrame = None
        self.obsoleteFrame = None
        self.scrollbarY = None

        width = self.model.db.config.getint('general', 'screen_width')
        width = None if width == -1 else width
        height = self.model.db.config.getint('general', 'screen_height')
        height = None if height == -1 else height
        super().__init__(width, height, log)

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
                '(physical printouts in the store).'))

        self.__addCategoryFrame(self.activeFrame, 'New', None, 'active',
                ('These sheets belong to new products or are replacements for '
                'existing sheets - print them out and bring them to the store.'),
                ('Remove', 'obsolete')
                ).config(background='tan1')

        self.__addCategoryFrame(self.activeFrame, 'Activated', 'inactive',
                'active',
                ('Formerly inactive sheets that should be available to '
                'customers again. Bring them to the store.'),
                ('Deactivate', 'inactive')
                ).config(background='tan1')

        self.__addCategoryFrame(self.activeFrame, 'Unchanged', 'active',
                'active',
                ('Active sheets that are already available in the store. '
                 'Nothing to do.'),
                ('Deactivate', 'inactive')
                ).config(background='green')

    def populateInactiveFrame(self):
        inactiveLabel = tkinter.Label(self.inactiveFrame, text='Inactive sheets')
        inactiveLabel.pack(side=tkinter.TOP, fill=tkinter.X, padx = self.padx, pady = self.pady)
        gui_components.ToolTip(inactiveLabel,
                ('These sheets should be kept somewhere out of customers'
                ' reach, ready for reuse when new stock arrives.'))

        self.__addCategoryFrame(self.inactiveFrame, 'New', 'active', 'inactive',
                ('These sheets became inactive (product sold out).\n'
                'Remove them from the store and keep them somewhere for later '
                'reuse.'),
                ('Activate', 'active')
                ).config(background='tan1')

        self.__addCategoryFrame(self.inactiveFrame, 'Unchanged',
                'inactive', 'inactive',
                ('These sheets were already inactive after last accounting, '
                'just keep them for later reuse.'),
                ('Activate', 'active')
                ).config(background='green')

    def populateObsoleteFrame(self):
        obsoleteLabel = tkinter.Label(self.obsoleteFrame, text='Obsolete sheets')
        obsoleteLabel.pack(side=tkinter.TOP, fill=tkinter.X, padx = self.padx, pady = self.pady)
        gui_components.ToolTip(obsoleteLabel,
                ('These sheets are full and should be removed and destroyed '
                'or archived.'))

        self.__addCategoryFrame(self.obsoleteFrame, 'Removed from active',
                'active', 'obsolete',
                ('These formerly active sheets are not needed any more. '
                'Remove them from the store and archive or throw them away.'),
                ).config(background='tan1')

        self.__addCategoryFrame(self.obsoleteFrame, 'Removed from inactive',
                'inactive', 'obsolete',
                ('These previously inactive sheets cannot be used any more. '
                'Archive or throw them away.'),
                ).config(background='tan1')

        self.__addCategoryFrame(self.obsoleteFrame, 'Proposed but discarded',
                None, 'obsolete',
                ('These sheets were proposed to be generated by tagtrail_gen '
                '(they should be generated to have enough tags available for '
                "quantity in products.csv), but you removed them. They won't "
                'be created unless you activate them again.'),
                ('Activate', 'active')
                ).config(background='tan1')

    def __addCategoryFrame(self, parent, title, previousState, newState,
            tooltip, button1 = None):
        """
        Add a frame with all sheets with a given previous and new state.

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
        :param button1: (text, newState) to initialize a button
        which sets the corresponding sheet to another newState
        :type button1: pair (str, str, str)
        :return: created frame
        :rtype: tkinter.Frame
        """
        frame = tkinter.Frame(parent)
        tkinter.Label(frame, text=title).grid(row=0, column=0)
        rowIdx = 0
        for sheet in self.model.sheets:
            if sheet.previousState != previousState or sheet.newState != newState:
                continue
            rowIdx += 1
            tkinter.Label(frame, text=sheet.filename).grid(
                    row=rowIdx, column=0, padx = self.padx, pady = self.pady)

            if button1 is not None:
                b = tkinter.Button(frame, text=button1[0])
                command = functools.partial(self.__setSheetNewState, sheet,
                        button1[1])
                b.bind('<Button-1>', command)
                b.bind('<Return>', command)
                b.grid(row=rowIdx, column=1)

        frame.pack(side=tkinter.TOP, fill=tkinter.X, padx = self.padx, pady = self.pady)
        frame.config(relief=tkinter.GROOVE, bd=2)
        gui_components.ToolTip(frame, tooltip)
        frame.update()
        return frame

    def __setSheetNewState(self, sheet, newState, event):
        """
        Set the newState of sheet, to be passed to buttons

        :param sheet: sheet
        :type sheet: :class:`ProductSheet`
        :param category: newState, one of ('active', 'inactive', 'obsolete')
        :type category: str
        :param event: tkinter event
        """
        if newState not in ['active', 'inactive', 'obsolete']:
            raise ValueError(f'invalid category: {newState}')
        sheet.newState = newState
        self.populateRoot()

    def saveAndQuit(self, event = None):
        try:
            self.model.save()
        finally:
            self.root.quit()

    def cancelAndQuit(self, event = None):
        self.root.quit()

if __name__== "__main__":
    parser = argparse.ArgumentParser(description='Generate empty product sheets')
    parser.add_argument('rootDir',
            help='Top-level tagtrail directory to process, usually data/next/')
    parser.add_argument('--allowRemoval',
            action='store_true',
            default=False,
            help=('''Allow tagtrail_gen to remove active product sheets.
            This should only be allowed directly after running
            tagtrail_account (customers could not add new tags yet).
            If removal is not allowed, it might not be possible to add
            the desired quantity of a product. If this is the case,
            tagtrail_gen shows an error and aborts.'''))
    parser.add_argument('--genDate',
            dest='genDate',
            type=helpers.DateUtility.strptime,
            default=helpers.DateUtility.todayStr(),
            help="Date of sheet generation, fmt='YYYY-mm-dd'",
            )
    parser.add_argument('--renamedRootDir',
            dest='renamedRootDir',
            default='data/gen_{genDate}/',
            help="New name to rename rootDir to. {genDate} " + \
                 "will be replaced by the value of the 'genDate' argument.")
    parser.add_argument('--nextDir',
            dest='nextDir',
            default='data/next/',
            help=('Name of the top-level tagtrail directory to be created '
                'for the next call to tagtrail_account/tagtrail_gen.'))
    args = parser.parse_args()

    renamedRootDir = args.renamedRootDir.format(genDate = args.genDate)
    if renamedRootDir == args.nextDir:
        raise ValueError(f'nextDir must not be named {renamedRootDir}')
    model = Model(args.rootDir, args.allowRemoval, args.genDate,
            renamedRootDir, args.nextDir)
    model.initializeSheets()
    GUI(model)

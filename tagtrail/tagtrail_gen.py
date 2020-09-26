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
from . import gui_components

class Gui:
    scanPostfix = '_normalized_scan.jpg'

    def __init__(self, accountingDataPath, addTestTags):
        self.log = helpers.Log()
        self.accountingDataPath = accountingDataPath
        self.addTestTags = addTestTags

        self.accountedProductsDir = f'{self.accountingDataPath}0_input/accounted_products'
        self.backupDir = f'{self.accountingDataPath}0_input/accounted_products_backup'
        if os.path.exists(self.backupDir):
            raise ValueError(f"""Unable to invoke tagtrail_gen again, as a backup
            directory already exists. To rerun tagtrail_gen, first decide if
            you want to use the backup or the already processed
            accounted_products (files might have been deleted here).\n
            To use {self.backupDir}, rename it to {self.accountedProductsDir}.\n
            To use {self.accountedProductsDir}, simply delete {self.backupDir}.""")

        self.root = tkinter.Tk()
        self.root.report_callback_exception = self.reportCallbackException
        self.root.geometry(str(self.root.winfo_screenwidth())+'x'+str(self.root.winfo_screenheight()))

        self.db = Database(f'{accountingDataPath}0_input/')

        self.accountedSheetFileNames= list(sorted(
            map(lambda f: os.path.splitext(f)[0],
            filter(lambda f: os.path.splitext(f)[1] == '.csv',
            next(os.walk(f'{accountingDataPath}0_input/accounted_products'))[2]))))
        self.accountedProductIds = set([self.productIdFromSheetFileName(sheetFileName) for
            sheetFileName in self.accountedSheetFileNames])
        self.initializeSheetLists()

        overviewToBePrinted = gui_components.Checkbar(self.root,
                'New accounted sheets to be generated:',
                self.sheetFileNamesToBePrintedNew, False)
        overviewToBePrinted.pack(side=tkinter.TOP, fill=tkinter.BOTH, expand=tkinter.YES, padx=5, pady=5)
        overviewToBePrinted.config(relief=tkinter.GROOVE, bd=2)

        overviewToBeReplaced = gui_components.Checkbar(self.root,
                'Accounted sheets to be replaced (make sure to replace them physically!):',
                self.sheetFileNamesToBeReplaced, False)
        overviewToBeReplaced.pack(side=tkinter.TOP, fill=tkinter.BOTH, expand=tkinter.YES, padx=5, pady=5)
        overviewToBeReplaced.config(relief=tkinter.GROOVE, bd=2)

        overviewToBeRemoved = gui_components.Checkbar(self.root,
                'Accounted sheets to be removed (make sure to remove them physically!):',
                self.sheetFileNamesToBeRemoved, False)
        overviewToBeRemoved.pack(side=tkinter.TOP, fill=tkinter.BOTH, expand=tkinter.YES, padx=5, pady=5)
        overviewToBeRemoved.config(relief=tkinter.GROOVE, bd=2)

        overviewToBeKept = gui_components.Checkbar(self.root,
                'Accounted sheets to be kept - these should also be around physically:',
                self.sheetFileNamesToBeKept, False)
        overviewToBeKept.pack(side=tkinter.TOP, fill=tkinter.BOTH, expand=tkinter.YES, padx=5, pady=5)
        overviewToBeKept.config(relief=tkinter.GROOVE, bd=2)

        overviewMissingProducts = gui_components.Checkbar(self.root,
                'Missing, non-empty products - add them to be generated and rerun tagtrail_gen:',
                self.missingProductIds, False)
        overviewMissingProducts.pack(side=tkinter.TOP, fill=tkinter.BOTH, expand=tkinter.YES, padx=5, pady=5)
        overviewMissingProducts.config(relief=tkinter.GROOVE, bd=2)

        buttonFrame = tkinter.Frame(self.root)
        buttonFrame.pack(side=tkinter.BOTTOM, pady=5)
        cancelButton = tkinter.Button(buttonFrame, text='Cancel',
                command=self.root.quit)
        cancelButton.pack(side=tkinter.LEFT)
        cancelButton.bind('<Return>', lambda _: self.root.quit())
        saveButton = tkinter.Button(buttonFrame, text='Save and Quit',
                command=self.saveAndQuit)
        saveButton.pack(side=tkinter.RIGHT)
        saveButton.bind('<Return>', lambda _: self.saveAndQuit())
        saveButton.focus_set()
        self.root.mainloop()

    def reportCallbackException(self, exception, value, tb):
        traceback.print_exception(exception, value, tb)
        messagebox.showerror('Abort Generation', value)

    def saveAndQuit(self):
        try:
            self.writeAndRemoveSheets()
        finally:
            self.root.quit()

    def initializeSheetLists(self):
        self.sheetFileNamesToBePrintedNew = []
        self.sheetFileNamesToBeReplaced = []
        self.sheetFileNamesToBeKept = []
        self.sheetFileNamesToBeRemoved = []
        self.missingProductIds = []

        maxNumSheets = self.db.config.getint('tagtrail_gen',
                'max_num_sheets_per_product')
        for productId, product in self.db.products.items():
            if not product.sheetsToPrint:
                if productId in self.accountedProductIds:
                    for sheetFileName in self.accountedSheetFileNames:
                        if self.productIdFromSheetFileName(sheetFileName) != productId:
                            continue
                        if product.expectedQuantity <= 0:
                            self.sheetFileNamesToBeRemoved.append(sheetFileName)
                        else:
                            self.sheetFileNamesToBeKept.append(sheetFileName)
                elif product.expectedQuantity > 0:
                    self.missingProductIds.append(productId)
            elif len(product.sheetsToPrint) == 1 and product.sheetsToPrint[0] == 'all':
                # one based, as this goes out to customers
                numSheets = math.ceil(product.expectedQuantity /
                        ProductSheet.maxQuantity())
                if numSheets > maxNumSheets:
                    raise ValueError(f'Quantity of {product.id} is too high, ' +
                            f'would need {numSheets}, max {maxNumSheets} are allowed')
                for sheetNumber in range(1, numSheets+1):
                    self.addSheetToBeGenerated(product, sheetNumber)

                # remove additional accountedSheetFileNames for this product
                for sheetFileName in self.accountedSheetFileNames:
                    if (self.productIdFromSheetFileName(sheetFileName) == productId and
                            not sheetFileName in self.sheetFileNamesToBeReplaced):
                        self.sheetFileNamesToBeRemoved.append(sheetFileName)
            else:
                for sheetNumberStr in product.sheetsToPrint:
                    try:
                        sheetNumber = int(sheetNumberStr)
                    except:
                        raise ValueError('Sheet numbers to print must be ' +
                                'one of "", "all" or a list of integers;' +
                                f'{product.sheetsToPrint} is invalid')
                    if sheetNumber > maxNumSheets:
                        raise ValueError(f'Sheet number {sheetNumber} of {product.id} is too high, ' +
                                f'max {maxNumSheets} are allowed')
                    self.addSheetToBeGenerated(product, sheetNumber)

                # keep additional accountedSheetFileNames for this product
                for sheetFileName in self.accountedSheetFileNames:
                    if (self.productIdFromSheetFileName(sheetFileName) == productId and
                            not sheetFileName in self.sheetFileNamesToBeReplaced):
                        self.sheetFileNamesToBeKept.append(sheetFileName)

    def addSheetToBeGenerated(self, product, sheetNumber):
        sheetFileName = product.id + '_' + self.db.config.get('tagtrail_gen',
                'sheet_number_string').format(sheetNumber=str(sheetNumber)).upper()
        if sheetFileName in self.accountedSheetFileNames:
            self.sheetFileNamesToBeReplaced.append(sheetFileName)
        else:
            self.sheetFileNamesToBePrintedNew.append(sheetFileName)

    def writeAndRemoveSheets(self):
        shutil.copytree(self.accountedProductsDir, self.backupDir)

        sheetDir = f'{self.accountingDataPath}1_emptySheets/'
        generatedProductsDir = f'{sheetDir}products/'
        helpers.recreateDir(sheetDir)
        helpers.recreateDir(generatedProductsDir)

        for sheetFileName in self.sheetFileNamesToBeReplaced + self.sheetFileNamesToBePrintedNew:
            path = f'{generatedProductsDir}{sheetFileName}.jpg'
            sheet = self.generateSheet(sheetFileName)
            if cv.imwrite(path, sheet.createImg()) is True:
                self.log.info(f'generated sheet {path}')
            else:
                raise ValueError(f'failed to generate sheet {path}')

        for sheetFileName in self.sheetFileNamesToBeReplaced + self.sheetFileNamesToBeRemoved:
            path = f'{self.accountedProductsDir}/{sheetFileName}.csv'
            self.log.info(f'removing sheet {path}')
            os.path.os.remove(f'{path}')
            os.path.os.remove(f'{path}{self.scanPostfix}')

        for productId in self.missingProductIds:
            self.log.info(f'Found a missing, non-empty product! {productId}')

    def generateSheet(self, sheetFileName):
        productId = self.productIdFromSheetFileName(sheetFileName)
        sheetNumber = self.sheetNumberFromSheetFileName(sheetFileName)
        product = self.db.products[productId]
        sheet = ProductSheet(self.db, self.addTestTags)
        sheet.name = product.description
        sheet.amountAndUnit = product.amountAndUnit
        sheet.grossSalesPrice = helpers.formatPrice(
                product.grossSalesPrice(),
                self.db.config.get('general', 'currency'))
        sheet.sheetNumber = self.db.config.get('tagtrail_gen',
                'sheet_number_string').format(sheetNumber=str(sheetNumber))
        return sheet

    def productIdFromSheetFileName(self, sheetFileName):
        productId, _ = sheetFileName.split('_')
        return productId

    def sheetNumberFromSheetFileName(self, sheetFileName):
        _, sheetNumberStr = sheetFileName.split('_')
        ints = [int(s) for s in sheetNumberStr.split() if s.isdigit()]
        assert(len(ints) == 1)
        assert(self.db.config.get('tagtrail_gen',
            'sheet_number_string').format(sheetNumber=str(ints[0])).upper() ==
            sheetNumberStr)
        return ints[0]

if __name__== "__main__":
    parser = argparse.ArgumentParser(description='Generate empty product and tag sheets')
    parser.add_argument('accountingDir',
            help='Top-level tagtrail directory to process, usually data/next/')
    parser.add_argument('--addTestTags',
            action='store_true',
            help='Already add some tags on the generated product sheets for testing purposes')
    args = parser.parse_args()
    Gui(args.accountingDir, args.addTestTags)

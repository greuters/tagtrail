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
import math
import os
import shutil
import logging

from . import helpers
from .database import Database
from .sheets import ProductSheet
from . import sheet_categorizer

class GenSheetCategorizer(sheet_categorizer.SheetCategorizer):
    def _checkPreconditions(self):
        # check no sheets have been removed from products.csv, unless user
        # asserts that accounting was done
        activeSheetDir = f'{self.rootDir}0_input/sheets/active/'
        inactiveSheetDir = f'{self.rootDir}0_input/sheets/inactive/'
        if not self.allowRemoval:
            for fileDir, filename in (
                    [(activeSheetDir, fn) for fn in os.listdir(activeSheetDir)] +
                    [(inactiveSheetDir, fn) for fn in os.listdir(inactiveSheetDir)]):
                productId = ProductSheet.productId_from_filename(filename)
                if productId not in self.db.products:
                    raise ValueError(f"Product '{productId}' has sheet "
                            f"'{fileDir+filename}', but is missing in products.csv.\n"
                            'If you have just done tagtrail_account (no tags could '
                            'have been added since) and you want to remove the '
                            'product, run tagtrail_gen with --allowRemoval option.\n'
                            'If you are not sure if tags have been added since '
                            'last accounting, re-add the product to products.csv '
                            'and run tagtrail_account first.')

        super()._checkPreconditions()

class Model():
    """
    Model class exposing all functionality needed to generate new ProductSheets
    """
    def __init__(self,
            rootDir,
            allowRemoval,
            genDate,
            renamedRootDir,
            nextDir):
        self.rootDir = rootDir
        self.allowRemoval = allowRemoval
        self.genDate = genDate
        self.renamedRootDir = renamedRootDir
        self.nextDir = nextDir
        self.logger = logging.getLogger('tagtrail.tagtrail_gen.Model')
        self.db = Database(f'{rootDir}0_input/')

        if self.db.products.inventoryQuantityDate is not None:
            raise ValueError(f'inventoryQuantityDate: {self.db.products.inventoryQuantityDate} '
                    'is not None\n'
                    'To do an inventory, run tagtrail_account - if you also '
                    'want to add new products, run tagtrail_gen afterwards on '
                    'the new next/ directory')

        if os.path.exists(self.renamedRootDir):
            raise ValueError(f'{self.renamedRootDir} already exists!')

    def initializeSheets(self):
        activeInputSheets = self.product_sheets_in_dir(f'{self.rootDir}0_input/sheets/active/')
        inactiveInputSheets = self.product_sheets_in_dir(f'{self.rootDir}0_input/sheets/inactive/')
        for key in activeInputSheets.keys():
            if key in inactiveInputSheets:
                raise ValueError(f'sheet exists in active as well as '
                        'inactive input sheets: {key}')

        self.sheetCategorizer = GenSheetCategorizer(
                self.rootDir,
                self.db,
                activeInputSheets,
                inactiveInputSheets,
                None, self.allowRemoval)

    def product_sheets_in_dir(self, inputDir):
        """
        Load all product sheets in a directory

        :param inputDir: directory to check
        :type inputDir: str
        :return: list of loaded product sheets
        :rtype: list of :class: `sheets.ProductSheet`
        """
        sheets = {}
        for filename in os.listdir(inputDir):
                sheet = ProductSheet()
                sheet.load(inputDir + filename)
                key = (sheet.productId(), sheet.sheetNumber)
                if (self.allowRemoval and sheet.productId() not in
                        self.db.products):
                    continue
                if key in sheets:
                    raise ValueError(f'duplicate sheet {inputDir + filename}')
                sheets[key] = sheet
        return sheets

    def save(self):
        self.sheetCategorizer.writeSheets()
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
        helpers.recreateDir(f'{self.nextDir}0_input/sheets')
        shutil.copytree(f'{self.renamedRootDir}5_output/sheets/active',
                f'{self.nextDir}0_input/sheets/active')
        shutil.copytree(f'{self.renamedRootDir}5_output/sheets/inactive',
                f'{self.nextDir}0_input/sheets/inactive')
        self.db.writeCsv(f'{self.nextDir}0_input/products.csv',
                self.db.products.copyForNext(self.genDate, True, False))

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
    parser.add_argument('--logLevel', dest='logLevel',
            help='Log level to write to console', default='INFO')
    args = parser.parse_args()
    helpers.configureLogger(logging.getLogger('tagtrail'), consoleLevel =
            logging.getLevelName(args.logLevel))

    renamedRootDir = args.renamedRootDir.format(genDate = args.genDate)
    if renamedRootDir == args.nextDir:
        raise ValueError(f'nextDir must not be named {renamedRootDir}')
    model = Model(args.rootDir, args.allowRemoval, args.genDate,
            renamedRootDir, args.nextDir)
    model.initializeSheets()
    sheet_categorizer.CategorizerGUI(model)

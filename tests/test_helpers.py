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
from .context import database
from .context import helpers
from .context import sheets

import os
import random
import unittest
from decimal import Decimal

class TagtrailTestCase(unittest.TestCase):
    def create_active_test_product(self, db):
        """
        Create a new Product with expectedQuantity > 0 and an empty active
        input sheet

        :param db: database to add the product to and read configuration
        :type db: :class: `database.Database`
        :return: the new product and sheet
        :rtype: (:class: `database.Product`, :class: `sheets.ProductSheet`)
        """
        testProduct = database.Product('test product', 100, 'g',
                Decimal(12.3), Decimal(.05), 50,
                addedQuantity = 0, soldQuantity = 0)
        db.products[testProduct.id] = testProduct
        sheet = self.generateProductSheet(db.config, testProduct, 1)
        sheet.store(f'{self.testRootDir}/0_input/sheets/active/')
        return (testProduct, sheet)

    def create_inactive_test_product(self, db):
        """
        Create a new Product with expectedQuantity <= 0 and an empty inactive
        input sheet

        :param db: database to add the product to and read configuration
        :type db: :class: `database.Database`
        :return: the new product and sheet
        :rtype: (:class: `database.Product`, :class: `sheets.ProductSheet`)
        """
        testProduct = database.Product('test product', 100, 'kg',
                Decimal(1.3), Decimal(.05), -3,
                addedQuantity = 0, soldQuantity = 0)
        db.products[testProduct.id] = testProduct
        sheet = self.generateProductSheet(db.config, testProduct, 1)
        sheet.store(f'{self.testRootDir}/0_input/sheets/inactive/')
        return (testProduct, sheet)

    def add_tags_to_product_sheet(self, sheet, memberIds, maxNumTagsToAdd):
        """
        Add random tags to a product sheet

        :param sheet: sheet to add tags to
        :type sheet: :class: `sheets.ProductSheet`
        :param memberIds: list of memberIds to choose from
        :type memberIds: list of str
        :param maxNumTagsToAdd: how many tags to add at most. Actual number of
            tags added is smaller if not enough free data boxes are available
        :type maxNumTagsToAdd: int
        :return: dictionary {memberId -> numTagsAdded} of number of tags added per member
        :rtype: dict {str -> int}
        """
        tagsPerMember = {memberId: 0 for memberId in memberIds}
        numTagsAdded = 0
        for box in sheet.dataBoxes():
            if numTagsAdded == maxNumTagsToAdd:
                break
            if box.text != '':
                continue
            memberId = random.choice(memberIds)
            tagsPerMember[memberId] += 1
            box.text = memberId
            box.confidence = 1
            numTagsAdded += 1
        return tagsPerMember

    def generateProductSheet(self, config, product, sheetNumber):
        """
        Generate a new :class: `sheets.ProductSheet`

        :param config: configuration specifying currency and sheetNumber format
        :type config: :class: `configparser.ConfigParser`
        :param product: the product to generate a sheet for
        :type product: :class: `database.Product`
        :param sheetNumber: number of the sheet
        :type sheetNumber: int
        :return: a new product sheet
        :rtype: :class: `sheets.ProductSheet`
        """
        sheet = sheets.ProductSheet()
        sheet.name = product.description
        sheet.amountAndUnit = product.amountAndUnit
        sheet.grossSalesPrice = helpers.formatPrice(
                product.grossSalesPrice(),
                config.get('general', 'currency'))
        sheet.sheetNumber = config.get('tagtrail_gen',
                'sheet_number_string').format(sheetNumber=str(sheetNumber))
        return sheet

    def check_sheets_in_dir(self, templateDir, testDir, excludedProductIds):
        """
        Check that all files in templateDir and testDir are equivalent and
        exist in both, apart from the excluded ones.

        :param templateDir: directory of the template sheets
        :type templateDir: str
        :param testDir: directory of the tested sheets
        :type testDir: str
        :param excludedProductIds: productIds to be excluded from the comparison
        :type excludedProductIds: list of str
        """
        self.check_files_in_dir(templateDir, testDir, lambda filename:
                sheets.ProductSheet.productId_from_filename(filename) not in
                excludedProductIds)

    def check_bills_in_dir(self, templateDir, testDir, excludedMemberIds):
        """
        Check that all bills in templateDir and testDir are equivalent and
        exist in both, apart from the excluded ones.

        :param templateDir: directory of the template sheets
        :type templateDir: str
        :param testDir: directory of the tested sheets
        :type testDir: str
        :param excludedMemberIds: memberIds to be excluded from the comparison
        :type excludedMemberIds: list of str
        """
        self.check_files_in_dir(templateDir, testDir,
                lambda filename: filename.split('.')[0] not in excludedMemberIds)

    def check_files_in_dir(self, templateDir, testDir, filenameFilter):
        """
        Check that all files in templateDir and testDir are equivalent and
        exist in both, apart from the ones excluded by filenameFilter.

        :param templateDir: directory of the template files
        :type templateDir: str
        :param testDir: directory of the tested files
        :type testDir: str
        :param filenameFilter: filter query to decide if a filename should be
            excluded (filenameFilter returns False) or not
        :type filenameFilter: function(str) -> bool
        """
        testedFilenames = os.listdir(testDir)

        # make sure no template files are missed
        for filename in os.listdir(templateDir):
            if not filenameFilter(filename):
                continue
            self.assertIn(filename, sorted(testedFilenames))

        testedFilenames = list(filter(filenameFilter, testedFilenames))

        for filename in testedFilenames:
            self.assert_file_equality(f'{templateDir}/{filename}',
                f'{testDir}/{filename}')

    def assert_file_equality(self, path1, path2):
        """
        Check that files at path1 and path2 are the same.

        For text files, this compares line by line to avoid issues with line
        break encoding on different platforms (e.g. template file written on
        linux, test run on windows).

        If a file cannot be decoded as utf-8, it is compared in binary mode.

        :param path1: path to first file
        :type path1: str
        :param path2: path to second file
        :type path2: str
        """
        try:
            with open(path1, 'r') as file1, open(path2, 'r') as file2:
                line1 = line2 = True
                while line1 and line2:
                    line1 = file1.readline()
                    line2 = file2.readline()
                    self.assertEqual(line1, line2,
                            f"""{path1} and {path2} differ in the following line:
                                {line1} != {line2}""")
                    self.assertEqual(line1, line2,
                        f'{path1} and {path2} have different numbers of lines')
        except UnicodeDecodeError:
            with open(path1, 'rb') as file1, open(path2, 'rb') as file2:
                chunkSize = 1000
                chunk1 = chunk2 = True
                while chunk1 and chunk2:
                    chunk1 = file1.read(chunkSize)
                    chunk2 = file2.read(chunkSize)
                    self.assertEqual(chunk1, chunk2,
                            f'{path1} and {path2} differ (binary comparison)')

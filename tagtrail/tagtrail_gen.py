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
import helpers
import math
from database import Database
from sheets import ProductSheet

def generateSheet(sheetDir, sheetName, db):
    log = helpers.Log()
    if sheetName in db.products:
        product = db.products[sheetName]
        numPages = math.ceil(product.previousQuantity /
                ProductSheet.maxQuantity())
        for pageNumber in range(1, numPages+1):
            sheet = ProductSheet(db, True)
            sheet.name = product.description
            sheet.amountAndUnit = product.amountAndUnit
            sheet.grossSalesPrice = helpers.formatPrice(product.grossSalesPrice())
            sheet.pageNumber = str(pageNumber)
            path = f'{sheetDir}{sheetName}_{pageNumber}.jpg'

            if cv.imwrite(path, sheet.createImg()) is True:
                log.info(f'generated sheet {path}')
            else:
                raise ValueError(f'failed to generate sheet at {path}')

    elif sheetDescription in db.members:
        member = db.members[sheetDescription]
        # TODO: implement TagSheet
    else:
        log.error("nothing to do here, sheet {} not found".format(sheetName))

def main(accountingDir):
    sheetDir= f'{accountingDir}1_emptySheets/'
    productSheetDir = f'{sheetDir}products/'
    tagSheetDir = f'{sheetDir}members/'
    helpers.recreateDir(sheetDir)
    helpers.recreateDir(productSheetDir)
    helpers.recreateDir(tagSheetDir)

    db = Database(f'{accountingDir}0_input/')

    for productId, product in db.products.items():
        generateSheet(productSheetDir, productId, db)

    # TODO generate TagSheets

if __name__== "__main__":
    parser = argparse.ArgumentParser(description='Generate empty product and tag sheets')
    parser.add_argument('accountingDir',
            help='Top-level tagtrail directory to process, usually data/next/')
    args = parser.parse_args()
    main(args.accountingDir)

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

import cv2 as cv
import slugify
from database import Database
from sheets import ProductSheet
from helpers import Log

def generateSheet(dataFilePath, sheetName, db):
    log = Log()
    if sheetName in db._products:
        product = db._products[sheetName]
        pageNumber = 0
        for (q0, q1) in [(s, min(s+ProductSheet.maxQuantity(), product._quantity)-1) for s in
                range(0, product._quantity, ProductSheet.maxQuantity())]:
            pageNumber += 1
            sheet1 = ProductSheet(product._description, product._unit,
                    product._price, pageNumber, q1-q0+1, db, True)
            path = dataFilePath.format("sheets/{}_{}.jpg".format(sheetName,
                pageNumber))
            cv.imwrite(path, sheet1.createImg())
            log.info("generate sheet {}".format(path))

    elif sheetDescription in db._members:
        member = db._members[sheetDescription]
        # TODO: implement TagSheet
    else:
        log.error("nothing to do here, sheet {} not found".format(sheetName))

def main():
    # TODO add commandline arguments to generate all products, all members or
    # individual
    dataFilePath = 'data/{}'
    db = Database(dataFilePath.format('database/mitglieder.csv'),
            dataFilePath.format('database/produkte.csv'))

    for productName in db._products:
        generateSheet(dataFilePath, productName, db)

if __name__== "__main__":
    main()

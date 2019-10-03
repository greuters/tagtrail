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
from functools import partial
from tkinter import *
from abc import ABC, abstractmethod
import helpers
from sheets import ProductSheet
from database import Database
from tkinter import messagebox
import os
import shutil
import csv
from datetime import date

class TagCollector(ABC):
    skipCnt = 1
    csvDelimiter = ';'
    quotechar = '"'
    newline = ''

    def __init__(self, previousAccountingPath, currentAccountingPath, db, log = helpers.Log()):
        self.log = log
        self.db = db
        self.previousAccountingPath = previousAccountingPath
        self.currentAccountingPath = currentAccountingPath
        self.previousTags, _ = self.collectTagsPerProductPage(self.previousAccountingPath)
        self.currentTags, self.currentProductPagePaths = self.collectTagsPerProductPage(self.currentAccountingPath)
        self.tagsPerProduct = self.collectTagsPerProduct()
        self.productsPerMember = self.collectProductsPerMember()

    def collectProductsPerMember(self):
        productsPerMember = {} # memberId: [(productId, cnt), ..]
        for m in self.db._members.values():
            productsPerMember[m._id] = []
            for productId, tags in self.tagsPerProduct.items():
                tagCnt = len(list(filter(lambda tag: tag == m._id, tags)))
                self.log.debug('tags={}, memberId={}, tagCnt={}'.format(tags,
                    m._id, tagCnt))
                productsPerMember[m._id].append((productId, tagCnt))
        return productsPerMember

    def collectTagsPerProduct(self):
        changedTags = {}
        for key in self.currentTags.keys():
            if key not in self.previousTags:
                changedTags[key] = self.currentTags[key]
                continue
            assert(len(self.previousTags[key]) == len(self.currentTags[key]))
            self.log.debug('previousTags: {}'.format(self.previousTags[key]))
            self.log.debug('currentTags: {}'.format(self.currentTags[key]))
            changedTagIndices = [idx for idx, tag in enumerate(self.previousTags[key])
                    if self.currentTags[key][idx] != tag]
            self.log.debug('changedTagIndices: {}'.format(changedTagIndices))
            if list(filter(lambda idx: self.previousTags[key][idx] != '', changedTagIndices)):
                raise Exception(
                    """{1}{2}_{3}.csv has tags that changed compared to
                    {0}{2}_{3}.csv. This situation indicates a tagging error
                    and needs to be resolved manually (editing mentioned CSVs
                    in a text editor) or by running tagtrail_sanitize again
                    (overriding tags of {1}{2}_{3}.csv by those of {0}{2}_{3}.csv)."""
                    .format(self.previousAccountingPath, self.currentAccountingPath, key[0], key[1]))
            changedTags[key] = list(map(lambda idx: self.currentTags[key][idx],
                changedTagIndices))
            unknownTags = list(filter(
                    lambda tag: tag not in self.db._members.keys(),
                    changedTags[key]))
            if unknownTags:
                raise Exception(
                    """{}{}_{}.csv contains a tag for non-existent members '{}'. Run
                    tagtrail_sanitize before tagtrail_account!"""
                    .format(self.currentAccountingPath, key[0], key[1], unknownTags))
            self.log.debug('changed tags: {}'.format(changedTags[key]))

        tagsPerProduct = {}
        for productId, page in self.currentTags.keys():
            if productId not in tagsPerProduct:
                tagsPerProduct[productId] = []
            tagsPerProduct[productId] += changedTags[productId, page]
        self.log.debug('tagsPerProduct: {}'.format(tagsPerProduct.items()))
        return tagsPerProduct

    def collectTagsPerProductPage(self, path):
        productPagePaths = []
        csvFilePaths = []
        for (_, _, fileNames) in os.walk(path):
            csvFilePaths = sorted(filter(lambda f: os.path.splitext(f)[1] ==
                '.csv', fileNames))
            break
        if not csvFilePaths:
            return {}, {}

        tagsPerProductPage = {} # (productId, page): [memberId, ..]
        for filePath in csvFilePaths:
            productPagePaths.append(filePath)
            productId, page = os.path.splitext(filePath)[0].split('_')
            self.log.info('Collecting tags of file {}'.format(path+filePath))
            self.log.debug('productId={}, page={}'.format(productId, page))
            tagsPerProductPage[(productId, page)] = []
            with open(path+filePath, newline=self.newline) as csvFile:
                reader = csv.reader(csvFile, delimiter=self.csvDelimiter,
                        quotechar=self.quotechar)
                for cnt, row in enumerate(reader):
                    if cnt<self.skipCnt:
                        continue
                    self.log.debug("row={}", row)
                    boxName, memberId, confidence = row[0], row[1], float(row[2])
                    if boxName in ("marginBox", "nameBox", "unitBox", "priceBox", "pageNumberBox"):
                        continue
                    else:
                        if boxName.find("dataBox") == -1:
                            self.log.warn("skipped unexpected box, row = {}", row)
                            continue

                    if confidence != 1:
                        self.log.info("row={}", row)
                        raise Exception("""{} is not properly sanitized. Run
                            tagtrail_sanitize before tagtrail_account!"""
                            .format(csvFile))

                    tagsPerProductPage[(productId, page)].append(memberId)
            self.log.debug('Tags in {}: {}'.format(filePath,
                tagsPerProductPage[(productId, page)]))
        return (tagsPerProductPage, productPagePaths)

class Checkbar(Frame):
   def __init__(self, parent=None, title='', picks=[], available=True, side=TOP,
           anchor=CENTER):
        Frame.__init__(self, parent)
        Label(self, text=title).grid(row=0, column=0)
        self.vars = []
        numCols = 5
        for idx, pick in enumerate(picks):
            row = int(idx / numCols)
            col = idx - row * numCols + 1
            var = IntVar()
            chk = Checkbutton(self, text=pick, variable=var)
            if available:
                var.set(1)
            else:
                var.set(0)
                chk.config(state=DISABLED)
            chk.grid(row=row, column=col, sticky=W)
            self.vars.append(var)

   def state(self):
       return map((lambda var: var.get()), self.vars)

class Gui:
    def __init__(self, previousAccountingDate, currentAccountingDate,
            dataPath, db):
        self.log = helpers.Log()
        self.previousAccountingDate = previousAccountingDate
        self.currentAccountingDate = currentAccountingDate
        self.previousAccountingName = 'accounting_'+previousAccountingDate
        self.currentAccountingName = 'accounting_'+currentAccountingDate
        self.previousAccountingPath = '{}/{}/'.format(dataPath,
                self.previousAccountingName)
        self.currentAccountingPath = '{}/{}/'.format(dataPath,
                self.currentAccountingName)
        self.db = db

        self.root = Tk()
        self.root.geometry(str(self.root.winfo_screenwidth())+'x'+str(self.root.winfo_screenheight()))

        # read in all necessary files
        try:
            self.tagCollector = TagCollector(self.previousAccountingPath+'5_accounted_products/',
                    self.currentAccountingPath+'1_products/', db, self.log)

            # TODO: parse postFinance CSV
            self.payments = {'CAB': 123, 'MIR': 777}
        except Exception:
            # TODO implement correctly
            messagebox.showwarning('Abort Accounting', 'message') #e.message)
            self.root.quit()
            raise
        else:
            self.productSheetSelection = Checkbar(self.root,
                    'Accounted pages to keep:', self.tagCollector.currentProductPagePaths, True)
            self.productSheetSelection.pack(side=TOP, fill=BOTH, expand=YES, padx=5, pady=5)
            self.productSheetSelection.config(relief=GROOVE, bd=2)

            missingProducts = sorted([
                p._id for p in db._products.values()
                if '{}_0.csv'.format(p._id) not in self.tagCollector.currentProductPagePaths
                ])
            mp = Checkbar(self.root, 'Missing products:', missingProducts, False)
            mp.pack(side=TOP, fill=BOTH, expand=YES, padx=5, pady=5)
            mp.config(relief=GROOVE, bd=2)

            buttonFrame = Frame(self.root)
            buttonFrame.pack(side=BOTTOM, pady=5)
            quitButton = Button(buttonFrame, text='Cancel',
                    command=self.root.quit)
            quitButton.pack(side=LEFT)
            quitButton = Button(buttonFrame, text='Save and Quit',
                    command=self.saveAndQuit)
            quitButton.pack(side=RIGHT)
            self.root.mainloop()

    def saveAndQuit(self):
        try:
            self.writeMemberCSVs()
            self.writeTransactions()
            self.writeStatistics()
            self.copyAccountedSheets()
        except:
            self.root.quit()
            raise
        else:
            self.root.quit()

    def writeMemberCSVs(self):
        destPath = '{}2_bills/'.format(self.currentAccountingPath)
        helpers.recreateDir(destPath, self.log)

        for memberId in self.tagCollector.productsPerMember.keys():
            filePath = '{}{}.csv'.format(destPath, memberId)
            helpers.Log().info("storing member CSV {}".format(filePath))
            with open(filePath, "w+") as fout:
                fout.write("{};{};{};{}\n" .format("productId", "numTags",
                'unitPrice', 'totalPrice'))
                for (productId, cnt) in self.tagCollector.productsPerMember[memberId]:
                    price = self.db._products[productId]._price
                    if cnt > 0:
                        fout.write("{};{};{};{}\n".format(productId, cnt,
                            price, price * cnt))

    def writeTransactions(self):
        destPath = '{}3_gnucash/'.format(self.currentAccountingPath)
        helpers.recreateDir(destPath, self.log)

        filePath = '{}accounts.csv'.format(destPath)
        with open(filePath, "w+") as fout:
            helpers.Log().info("writing accounts {}".format(filePath))
            fmt = '{}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}\n'
            fout.write(fmt.format('type', 'full_name', 'name', 'code',
                'description', 'color', 'notes', 'commoditym',
                'commodityn', 'hidden', 'tax', 'place_holder'))
            for memberId in self.db._members.keys():
                fout.write(fmt.format('LIABILITY',
                'Fremdkapital:Guthaben Mitglieder:'+memberId, memberId,
                '', '', '', '', 'CHF', 'CURRENCY', 'F', 'F', 'F'))

        marginPercentage = 0.05
        filePath = '{}withdrawals.csv'.format(destPath)
        with open(filePath, "w+") as fout:
            helpers.Log().info("writing withdrawals {}".format(filePath))
            fout.write("{},{},{},{},{}\n"
                    .format("Date", "Description", "Account", "Deposit",
                        "Transfer Account"))
            for memberId in self.tagCollector.productsPerMember.keys():
                grossPrice = 0
                for (productId, cnt) in self.tagCollector.productsPerMember[memberId]:
                    grossPrice += self.db._products[productId]._price * cnt
                netPrice = grossPrice / (1 + marginPercentage)
                fout.write("{},{},{},{},{}\n"
                        .format(self.currentAccountingDate,
                            self.currentAccountingName, memberId,
                            helpers.formatPrice(helpers.roundPriceCH(netPrice)),
                            'Warenwert'))
                fout.write("{},{},{},{},{}\n"
                        .format(self.currentAccountingDate,
                            self.currentAccountingName, memberId,
                            helpers.formatPrice(helpers.roundPriceCH(grossPrice - netPrice)),
                            'Marge'))

        filePath = '{}payments.csv'.format(destPath)
        with open(filePath, "w+") as fout:
            helpers.Log().info("writing gnucash {}".format(filePath))
            fout.write("{},{},{},{},{}\n"
                    .format("Date", "Description", "Account", "Withdrawal",
                        "Transfer Account"))
            for memberId, payment in self.payments.items():
                fout.write("{},{},{},{},{}\n"
                        .format(date.today(), 'Einzahlung', memberId, payment,
                            'Girokonto'))

    def writeStatistics(self):
        destPath = '{}4_statistics/'.format(self.currentAccountingPath)
        helpers.recreateDir(destPath, self.log)
        print('not yet implemented')

    def copyAccountedSheets(self):
        productSheetsToKeep = list(zip(*filter(
            lambda pair: pair[0] == 1,
            zip(self.productSheetSelection.state(), self.tagCollector.currentProductPagePaths)
            )))[1]

        destPath = '{}5_accounted_products/'.format(self.currentAccountingPath)
        helpers.recreateDir(destPath, self.log)
        for productFileName in productSheetsToKeep:
            srcPath = '{}{}{}'.format(self.currentAccountingPath, '1_products/', productFileName)
            self.log.info("copy {} to {}".format(srcPath, destPath))
            shutil.copy(srcPath, destPath)

if __name__ == '__main__':
    dataPath = 'data'
    databasePath = '{}/database/{}'
    db = Database(databasePath.format(dataPath, 'mitglieder.csv'),
            databasePath.format(dataPath, 'produkte.csv'))
    Gui('2019-08-23', '2019-09-26', dataPath, db)

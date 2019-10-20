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
import database
from tkinter import messagebox
import traceback
import os
import shutil
import csv
import copy

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
            alreadyAccountedProductsPath,
            currentProductsToAccountPath,
            accountingDate,
            db, log = helpers.Log()):
        self.log = log
        self.db = db
        self.alreadyAccountedProductsPath = alreadyAccountedProductsPath
        self.currentProductsToAccountPath = currentProductsToAccountPath
        self.accountingDate = accountingDate
        self.alreadyAccountedSheets = self.loadProductSheets(self.alreadyAccountedProductsPath)
        self.currentSheets = self.loadProductSheets(self.currentProductsToAccountPath)
        self.newTagsPerProduct = self.collectNewTagsPerProduct()

    def currentProductPagePaths(self):
        return [sheet.filePath for sheet in self.currentSheets.values()]

    def currentGrossSalesPrice(self, productId):
        prices = [s.grossSalesPrice
                  for (pId, _), s in self.currentSheets.items()
                  if pId == productId]
        if len(set(prices)) != 1:
            raise AssertionError('should have exactly one price per ' + \
                    f'{productId}, but prices={prices}')
        return prices[0]

    def numNewTags(self, productId, memberIds):
        if productId in self.newTagsPerProduct:
            tags = self.newTagsPerProduct[productId]
            numTags = sum([1 for tag in tags if tag in memberIds])
            self.log.debug(f'tags={tags}, productId={productId}, ' + \
                    f'memberIds={memberIds}, numTags={numTags}')
            return numTags
        else:
            return 0

    def newTags(self, productId, pageNumber):
        key = (productId, pageNumber)
        alreadyAccountedTags = self.alreadyAccountedSheets[key].confidentTags()
        currentTags = self.currentSheets[key].confidentTags()
        assert(len(alreadyAccountedTags) == len(currentTags))
        self.log.debug(f'alreadyAccountedTags: {alreadyAccountedTags}')
        self.log.debug(f'currentTags: {currentTags}')

        changedIndices = [idx for idx, tag in enumerate(alreadyAccountedTags)
                if currentTags[idx] != tag]
        self.log.debug(f'changedIndices: {changedIndices}')
        offendingDataboxes = [f'dataBox{idx}' for idx in changedIndices if alreadyAccountedTags[idx] != '']
        if offendingDataboxes:
            self.log.error(f'offendingDataboxes: {offendingDataboxes}')
            raise ValueError(
                'Already accounted tags were changed in the ' + \
                'current accounting.\n\n' + \
                'This situation indicates a tagging error and has ' + \
                'to be resolved manually by correcting this file:\n\n' + \
                f'{self.currentProductsToAccountPath}{productId}_{pageNumber}.csv\n\n' + \
                'Offending data boxes:\n\n' + \
                f'{offendingDataboxes}\n\n' + \
                'Corresponding file from last accounting:\n\n' + \
                f'{self.alreadyAccountedProductsPath}{productId}_{pageNumber}.csv')

        return list(map(lambda idx: currentTags[idx], changedIndices))

    def collectNewTagsPerProduct(self):
        newTags = {}
        for key in self.currentSheets.keys():
            if key not in self.alreadyAccountedSheets:
                newTags[key] = self.currentSheets[key].confidentTags()
            else:
                newTags[key] = self.newTags(key[0], key[1])

            unknownTags = list(filter(
                    lambda tag: tag and tag not in self.db.members.keys(),
                    newTags[key]))
            if unknownTags:
                raise Exception(
                    f"{self.currentProductsToAccountPath}{key[0]}_{key[1]}.csv " + \
                    f"contains a tag for non-existent members '{unknownTags}'." + \
                    "Run tagtrail_sanitize before tagtrail_account!")
            self.log.debug(f'newTags[{key}]={newTags[key]}')

        newTagsPerProduct = {}
        for productId, pageNumber in self.currentSheets.keys():
            if productId not in newTagsPerProduct:
                newTagsPerProduct[productId] = []
            newTagsPerProduct[productId] += newTags[productId, pageNumber]
        self.log.debug(f'newTagsPerProduct: {newTagsPerProduct.items()}')
        return newTagsPerProduct

    def loadProductSheets(self, path):
        self.log.info(f'collecting tags in {path}')
        csvFilePaths = helpers.sortedFilesInDir(path, ext = '.csv')
        if not csvFilePaths:
            return {}

        productSheets = {}
        for filePath in csvFilePaths:
            productId, pageNumber = os.path.splitext(filePath)[0].split('_')
            self.log.debug(f'productId={productId}, pageNumber={pageNumber}')
            sheet = ProductSheet()
            sheet.load(path+filePath)
            sheet.filePath = filePath
            if sheet.productId() != productId:
                raise ValueError(f'{path+filePath} is invalid.\n' + \
                    '{sheet.productId()} != {productId}')
            if sheet.pageNumber != pageNumber:
                raise ValueError(f'{path+filePath} is invalid.\n' + \
                    '{sheet.pageNumber()} != {pageNumber}')
            if sheet.unconfidentTags():
                raise ValueError(
                    f'{path+filePath} is not properly sanitized.\n' + \
                    'Run tagtrail_sanitize before tagtrail_account!')
            if (productId, pageNumber) in productSheets:
                raise ValueError(
                    f'{(productId, pageNumber)} exists more than once')
            productSheets[(productId, pageNumber)] = sheet
            prices = [s.grossSalesPrice
                      for (pId, _), s in productSheets.items()
                      if pId == productId]
            if len(set(prices)) != 1:
                raise ValueError(
                    f'{productId} pages have different prices, {prices}')
        return productSheets

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
    def __init__(self, accountingDataPath, nextAccountingDataPath, accountingDate, db):
        self.log = helpers.Log()
        self.accountingDate = accountingDate
        self.accountingDataPath = accountingDataPath
        self.nextAccountingDataPath = nextAccountingDataPath
        self.db = db

        self.root = Tk()
        self.root.report_callback_exception = self.reportCallbackException
        self.root.geometry(str(self.root.winfo_screenwidth())+'x'+str(self.root.winfo_screenheight()))

        self.productSheetSelection = Checkbar(self.root,
                'Accounted pages to keep:',
                self.db.productPagePaths, True)
        self.productSheetSelection.pack(side=TOP, fill=BOTH, expand=YES, padx=5, pady=5)
        self.productSheetSelection.config(relief=GROOVE, bd=2)

        missingProducts = sorted([
            p.id for p in self.db.products.values()
            if '{}_1.csv'.format(p.id) not in
            self.db.productPagePaths
            ])
        mp = Checkbar(self.root, 'Missing products:', missingProducts, False)
        mp.pack(side=TOP, fill=BOTH, expand=YES, padx=5, pady=5)
        mp.config(relief=GROOVE, bd=2)

        buttonFrame = Frame(self.root)
        buttonFrame.pack(side=BOTTOM, pady=5)
        cancelButton = Button(buttonFrame, text='Cancel',
                command=self.root.quit)
        cancelButton.pack(side=LEFT)
        cancelButton.bind('<Return>', lambda _: self.root.quit())
        saveButton = Button(buttonFrame, text='Save and Quit',
                command=self.saveAndQuit)
        saveButton.pack(side=RIGHT)
        saveButton.bind('<Return>', lambda _: self.saveAndQuit())
        saveButton.focus_set()
        self.root.mainloop()

    def reportCallbackException(self, exception, value, tb):
        traceback.print_exception(exception, value, tb)
        messagebox.showerror('Abort Accounting', value)

    def saveAndQuit(self):
        try:
            self.writeBills()
            self.writeGnuCashFiles()
            self.prepareNextAccounting()
        finally:
            self.root.quit()

    def writeBills(self):
        destPath = f'{self.accountingDataPath}3_bills/'
        helpers.recreateDir(destPath, self.log)
        for member in self.db.members.values():
            database.Database.writeCsv(destPath+member.id+'.csv',
                    self.db.bills[member.id])

    def writeGnuCashFiles(self):
        destPath = f'{self.accountingDataPath}/4_gnucash/'
        helpers.recreateDir(destPath, self.log)
        database.Database.writeCsv(f'{destPath}accounts.csv', self.db.accounts)
        database.Database.writeCsv(f'{destPath}purchaseTransactions.csv',
                self.db.purchaseTransactions)
        database.Database.writeCsv(f'{destPath}paymentTransactions.csv',
                self.db.paymentTransactions)

    def prepareNextAccounting(self):
        helpers.recreateDir(self.nextAccountingDataPath, self.log)
        helpers.recreateDir(f'{self.nextAccountingDataPath}0_input', self.log)
        helpers.recreateDir(f'{self.nextAccountingDataPath}0_input/scans', self.log)
        helpers.recreateDir(f'{self.accountingDataPath}5_output/', self.log)
        self.writeMemberCSV()
        self.writeProductsCSVs()
        self.copyAccountedSheets()
        shutil.copytree(f'{self.accountingDataPath}0_input/templates',
                f'{self.nextAccountingDataPath}0_input/templates')

    def writeMemberCSV(self):
        newMembers = copy.deepcopy(self.db.members)
        for m in newMembers.values():
            m.balance = self.db.bills[m.id].currentBalance()
        database.Database.writeCsv(f'{self.nextAccountingDataPath}0_input/members.csv',
                newMembers)

    def writeProductsCSVs(self):
        database.Database.writeCsv(f'{self.accountingDataPath}5_output/products.csv',
                self.db.products)
        database.Database.writeCsv(f'{self.nextAccountingDataPath}0_input/products.csv',
                self.db.products.copyForNextAccounting(self.accountingDate))

    def copyAccountedSheets(self):
        productSheetsToKeep = list(zip(*filter(
            lambda pair: pair[0] == 1,
            zip(self.productSheetSelection.state(),
                self.db.productPagePaths)
            )))[1]

        destPath = self.nextAccountingDataPath+'0_input/accounted_products/'
        helpers.recreateDir(destPath, self.log)
        for productFileName in productSheetsToKeep:
            srcPath = self.accountingDataPath+'2_taggedProductSheets/'+productFileName
            self.log.info("copy {} to {}".format(srcPath, destPath))
            shutil.copy(srcPath, destPath)

class EnrichedDatabase(database.Database):
    # TODO move to config file
    merchandiseValue = 'Warenwert'
    merchandiseValueAccount = 'Warenwert'
    margin = 'Marge'
    marginAccount = 'Marge'
    payment = 'Einzahlung'
    giroAccount = 'Girokonto'

    def __init__(self, accountingDataPath, accountingDate):
        self.log = helpers.Log()
        self.accountingDataPath = accountingDataPath
        self.accountingDate = accountingDate
        super().__init__(f'{accountingDataPath}0_input/')

        payments = self.loadPayments()
        tagCollector = TagCollector(
                self.accountingDataPath+'0_input/accounted_products/',
                self.accountingDataPath+'2_taggedProductSheets/',
                self.accountingDate,
                self, self.log)

        self.products.expectedQuantityDate = self.accountingDate
        for productId, product in self.products.items():
            product.soldQuantity = tagCollector.numNewTags(productId,
                    list(self.members.keys()))

        self.bills = self.createBills(tagCollector, payments)
        self.productPagePaths = tagCollector.currentProductPagePaths()
        self.accounts = database.MemberAccountDict(
                {m.id: database.MemberAccount(m.id) for m in self.members.values()})
        self.purchaseTransactions = self.createPurchaseTransactions()
        self.paymentTransactions = self.createPaymentTransactions(payments)

    def loadPayments(self):
        # TODO: parse postFinance CSV
        # file:
        # export_Transactions_{self.previousAccountingDate}_{self.accountingDate}.csv
        return {member.id: 0 for member in self.members.values()}

    def createBills(self, tagCollector, paymentsPerMember):
        bills = {}
        for member in self.members.values():
            bill = database.Bill(member.id,
                    self.members.accountingDate,
                    self.accountingDate,
                    member.balance,
                    paymentsPerMember[member.id])
            for productId in tagCollector.newTagsPerProduct.keys():
                numTags = tagCollector.numNewTags(productId, [member.id])
                if numTags != 0:
                    position = database.BillPosition(productId,
                            self.products[productId].description,
                            numTags,
                            self.products[productId].purchasePrice,
                            tagCollector.currentGrossSalesPrice(productId),
                            0)
                    bill[position.id] = position
            bills[member.id] = bill
        return bills

    def createPurchaseTransactions(self):
        return database.TransactionDict({
            **{self.merchandiseValue+bill.memberId:
                database.Transaction(self.merchandiseValue+bill.memberId,
                f'{self.merchandiseValue} accounted on {self.accountingDate}',
                bill.totalPurchasePrice(),
                self.merchandiseValueAccount,
                bill.memberId)
                for bill in self.bills.values()},
            **{self.margin+bill.memberId:
                database.Transaction(self.margin+bill.memberId,
                f'{self.margin} accounted on {self.accountingDate}',
                bill.totalGrossSalesPrice()-bill.totalPurchasePrice(),
                self.marginAccount,
                bill.memberId)
                for bill in self.bills.values()}
            })

    def createPaymentTransactions(self, payments):
        return database.TransactionDict({
            bill.memberId:
                database.Transaction(bill.memberId,
                # TODO: better description
                f'{self.payment} accounted on {self.accountingDate}',
                payments[bill.memberId],
                bill.memberId,
                self.giroAccount)
                for bill in self.bills.values()})


if __name__ == '__main__':
    dataPath = 'data/'
    accountingDate = '2019-11-03'
    originalPath = f'{dataPath}next/'
    newPath = f'{dataPath}next/'
    #originalPath = f'{dataPath}next/'
    #newPath = f'{dataPath}accounting_{accountingDate}/'
    if originalPath != newPath:
        shutil.move(originalPath, newPath)

    db = EnrichedDatabase(newPath, accountingDate)
    Gui(newPath, f'{dataPath}next2/', accountingDate, db)

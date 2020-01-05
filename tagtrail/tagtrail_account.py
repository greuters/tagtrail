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
import helpers
import gui_components
from sheets import ProductSheet
import database
import tkinter
from tkinter import messagebox
import traceback
import datetime
import os
import shutil
import csv
import copy

# TODO: handle tags for non-existing products (i.e. somebody "bought" something
# that should not have been there any more) => should be accounted as negative
# SCHWUND

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

class Gui:
    def __init__(self, accountingDataPath, nextAccountingDataPath, accountingDate):
        self.log = helpers.Log()
        self.accountingDate = accountingDate
        self.accountingDataPath = accountingDataPath
        self.nextAccountingDataPath = nextAccountingDataPath

        self.root = tkinter.Tk()
        self.root.report_callback_exception = self.reportCallbackException
        self.root.geometry(str(self.root.winfo_screenwidth())+'x'+str(self.root.winfo_screenheight()))

        self.db = EnrichedDatabase(accountingDataPath, accountingDate)

        self.productSheetSelection = gui_components.Checkbar(self.root,
                'Accounted pages to keep:',
                self.db.productPagePaths, True)
        self.productSheetSelection.pack(side=tkinter.TOP, fill=tkinter.BOTH, expand=tkinter.YES, padx=5, pady=5)
        self.productSheetSelection.config(relief=tkinter.GROOVE, bd=2)

        missingProducts = sorted([
            p.id for p in self.db.products.values()
            if '{}_1.csv'.format(p.id) not in
            self.db.productPagePaths
            ])
        mp = gui_components.Checkbar(self.root, 'Missing products:', missingProducts, False)
        mp.pack(side=tkinter.TOP, fill=tkinter.BOTH, expand=tkinter.YES, padx=5, pady=5)
        mp.config(relief=tkinter.GROOVE, bd=2)

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
        database.Database.writeCsv(f'{destPath}accounts.csv', self.db.accounts)
        database.Database.writeCsv(f'{destPath}purchaseTransactions.csv',
                self.db.purchaseTransactions)
        database.Database.writeCsv(f'{destPath}paymentTransactions.csv',
                self.db.paymentTransactions)

    def prepareNextAccounting(self):
        helpers.recreateDir(self.nextAccountingDataPath, self.log)
        helpers.recreateDir(f'{self.nextAccountingDataPath}0_input', self.log)
        helpers.recreateDir(f'{self.nextAccountingDataPath}0_input/scans', self.log)
        self.writeMemberCSV()
        self.writeProductsCSVs()
        self.copyAccountedSheets()
        database.Database.writeCsv(f'{self.nextAccountingDataPath}0_input/correctionTransactions.csv',
                database.CorrectionTransactionDict())
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
        productSheetsToKeep = [path for selected, path in
                zip(self.productSheetSelection.state(),
                    self.db.productPagePaths)
                if selected == 1]
        self.log.debug(f'productSheetsToKeep = {productSheetsToKeep}')

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

    def __init__(self, accountingDataPath, accountingDate):
        self.log = helpers.Log()
        self.accountingDataPath = accountingDataPath
        self.accountingDate = accountingDate
        super().__init__(f'{accountingDataPath}0_input/')

        tagCollector = TagCollector(
                self.accountingDataPath+'0_input/accounted_products/',
                self.accountingDataPath+'2_taggedProductSheets/',
                self.accountingDate,
                self, self.log)

        self.products.expectedQuantityDate = self.accountingDate
        for productId, product in self.products.items():
            product.soldQuantity = tagCollector.numNewTags(productId,
                    list(self.members.keys()))

        self.correctionTransactions = database.Database.readCsv(
                self.accountingDataPath+'0_input/correctionTransactions.csv',
                database.CorrectionTransactionDict)
        self.paymentTransactions = self.loadPaymentTransactions()
        self.bills = self.createBills(tagCollector)
        self.productPagePaths = tagCollector.currentProductPagePaths()
        self.accounts = database.MemberAccountDict(
                {m.id: database.MemberAccount(m.id) for m in self.members.values()})
        self.purchaseTransactions = self.createPurchaseTransactions()

    def loadPaymentTransactions(self):
        toDate = self.accountingDate-datetime.timedelta(days=1)
        unprocessedTransactionsPath = self.accountingDataPath + \
                '5_output/unprocessed_Transactions_' + \
                helpers.DateUtility.strftime(self.previousAccountingDate) + '_' + \
                helpers.DateUtility.strftime(toDate) + '.csv'

        if not os.path.isfile(unprocessedTransactionsPath):
            raise Exception(
                f"{unprocessedTransactionsPath} does not exist.\n" + \
                "Run tagtrail_bankimport before tagtrail_account!")

        unprocessedPayments = [t.notificationText for t in
                database.Database.readCsv(unprocessedTransactionsPath,
                    database.PostfinanceTransactionList)
                 if not t.creditAmount is None]
        if unprocessedPayments != []:
            messagebox.showwarning('Unprocessed payments exist',
                'Following payments will not be documented for our members:\n\n'
                + '\n\n'.join(unprocessedPayments) + '\n\n'
                + 'Run tagtrail_bankimport again if you want to correct this.')

        return database.Database.readCsv(
                self.accountingDataPath+'4_gnucash/paymentTransactions.csv',
                database.GnucashTransactionList)

    def createBills(self, tagCollector):
        bills = {}
        for member in self.members.values():
            bill = database.Bill(member.id,
                    self.members.accountingDate,
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
        return database.GnucashTransactionList(
                *([database.GnucashTransaction(
                    f'{self.merchandiseValue} accounted on {self.accountingDate}',
                    bill.totalPurchasePrice(),
                    self.merchandiseValueAccount,
                    bill.memberId,
                    self.accountingDate) for bill in self.bills.values()]
                +
                [database.GnucashTransaction(
                    f'{self.margin} accounted on {self.accountingDate}',
                    bill.totalGrossSalesPrice()-bill.totalPurchasePrice(),
                    self.marginAccount,
                    bill.memberId,
                    self.accountingDate) for bill in self.bills.values()])
                )

    @property
    def previousAccountingDate(self):
        return self.members.accountingDate

def main(accountingDir, renamedAccountingDir, accountingDate, nextAccountingDir):
    newDir = renamedAccountingDir.format(accountingDate = accountingDate)
    if accountingDir != newDir:
        shutil.move(accountingDir, newDir)
    Gui(newDir, nextAccountingDir, accountingDate)

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
            default='data/accounting_{accountingDate}/',
            help="New name to rename accountingDir to. {accountingDate} " + \
                 "will be replaced by the value of the 'accountingDate' argument.")
    parser.add_argument('--nextAccountingDir',
            dest='nextAccountingDir',
            default='data/next/',
            help='Name of the top-level tagtrail directory to be created for the next accounting.')

    args = parser.parse_args()
    main(args.accountingDir, args.renamedAccountingDir, args.accountingDate, args.nextAccountingDir)

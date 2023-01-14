# -*- coding: utf-8 -*-

from .context import helpers
from .context import database
from .context import sheets
from .context import tagtrail_account
from .test_helpers import TagtrailTestCase

import logging
import argparse
import csv
import datetime
import unittest
import shutil
import os
import random
import slugify
from decimal import Decimal

class AccountTest(TagtrailTestCase):
    """ Tests of tagtrail_account """
    testDate = helpers.DateUtility.strptime('2021-04-01')
    testProductId = 'apfelringli'
    keyringPassword = None

    def setUp(self):
        if __name__ != '__main__':
            self.skipTest(reason = 'only run when invoked directly')
        self.baseSetUp('medium')

    def baseSetUp(self, templateName):
        self.templateName = templateName
        self.templateRootDir = f'tests/data/template_{self.templateName}/'
        self.templateAccountDir = f'tests/data/account_{self.templateName}/'
        self.templateNextDir = f'tests/data/account_next_{self.templateName}/'

        self.tmpDir = 'tests/tmp/'
        self.testRootDir = f'{self.tmpDir}{self.templateName}/'
        self.testAccountDir = f'{self.tmpDir}account_{self.templateName}/'
        self.testNextDir = f'{self.tmpDir}next_{self.templateName}/'

        self.logger = logging.getLogger('tagtrail.tests.scenario_account.AccountTest')
        self.logger.info(f'Starting test {self.id()}\n')
        helpers.recreateDir(self.tmpDir)
        shutil.copytree(self.templateRootDir, self.testRootDir)
        helpers.recreateDir(f'{self.testRootDir}3_bills')
        helpers.recreateDir(f'{self.testRootDir}5_output/sheets')
        self.config = database.Database(f'{self.testRootDir}0_input/').config

    def check_output(self, model, modifiedProductIds = [],
            modifiedMemberIds = []):
        """
        Check invariants on output files, and if they match the expected
        template output.

        :param model: model after initializing sheets and saving them
        :type model: :class: `tagtrail_account.Model`
        :param modifiedProductIds: ids of products that were modified before
            running tagtrail_account on the template and should therefore not be
            compared to template output
        :type  modifiedProductIds: list of str
        :param modifiedMemberIds: ids of members that were modified before
            running tagtrail_account on the template and should therefore not be
            compared to template output
        :type  modifiedMemberIds: list of str
        """
        self.logger.info(f'Accounting done, checking output\n')
        self.check_transaction_files_per_member(model)
        self.check_product_sheets(model)
        self.check_missing_sheets(model)
        self.check_output_matches_template(model, modifiedProductIds,
                modifiedMemberIds)
        self.check_members_tsv(model)
        self.check_products_csv(model)
        self.check_transactions(model)

    def check_transaction_files_per_member(self, model):
        """
        Check if each member appears in all necessary transactions and if a
        plausible bill exists.
        """
        self.logger.info(f'Check member transaction files')
        exportedAccounts = self.load_accounts_csv()
        (marginTransactions, merchandiseTransactions,
                paymentTransactions, _) = self.load_transactions_csv(model)
        correctionTransactions = model.db.readCsv(
                f'{self.testAccountDir}0_input/correctionTransactions.csv',
                database.CorrectionTransactionDict)

        for memberId in model.db.members:
            self.assertIn(memberId, exportedAccounts,
                f'{memberId} missing in exported accounts')
            self.assertIn(memberId, marginTransactions,
                f'transaction to margin account missing for {memberId}')
            self.assertIn(memberId, merchandiseTransactions,
                f'transaction to merchandise account missing for {memberId}')

            billPath = f'{self.testAccountDir}/3_bills/to_be_sent/{memberId}.csv'
            self.assertTrue(os.path.exists(billPath),
                f'bill for {memberId} missing')
            bill = model.db.readCsv(billPath, database.Bill)
            self.assertEqual(bill.totalPayments,
                    paymentTransactions[memberId] if memberId in
                    paymentTransactions else 0,
                    f'sum of payments of {memberId} differ from total in bill')
            self.assertEqual(bill.correctionTransaction,
                    correctionTransactions[memberId].amount if memberId in
                    correctionTransactions else 0,
                    f'input correction transaction for {memberId} differs '
                    'from amount in bill')

    def check_product_sheets(self, model):
        """
        Check if all product sheets are written to disc as claimed to the user.
        """
        self.logger.info(f'Check product sheets')
        inputSheetDir = f'{self.testAccountDir}0_input/sheets/'
        outputSheetDir = f'{self.testAccountDir}5_output/sheets/'
        taggedSheetDir = f'{self.testAccountDir}2_taggedProductSheets/'
        nextSheetDir = f'{self.testNextDir}0_input/sheets/'
        generatedSheetDir = f'{self.testAccountDir}1_generatedSheets/'

        for sheet in model.sheetCategorizer.activeSheetsToBePrinted:
            imgName = f'{sheet.filename[:-4]}.jpg'
            imgPath = f'{generatedSheetDir}{imgName}'
            self.assertTrue(os.path.exists(imgPath),
                f'new empty sheet {imgPath} missing')
            self.assertTrue(os.path.exists(
                f'{outputSheetDir}active/{sheet.filename}'),
                f'output for new sheet {sheet.filename} missing')
            self.assertTrue(len(sheet.emptyDataBoxes()) ==
                    sheets.ProductSheet.maxQuantity(),
                    'new replacing sheet is not empty')

        for sheet in model.sheetCategorizer.missingSheets:
            self.assert_file_equality(
                f'{inputSheetDir}active/{sheet.filename}',
                f'{outputSheetDir}active/{sheet.filename}')

        for sheet in model.sheetCategorizer.activeSheetsFromInactive:
            self.assert_file_equality(
                f'{inputSheetDir}inactive/{sheet.filename}',
                f'{outputSheetDir}active/{sheet.filename}')

        for sheet in model.sheetCategorizer.activeSheetsFromActive:
            self.assert_file_equality(
                f'{taggedSheetDir}{sheet.filename}',
                f'{outputSheetDir}active/{sheet.filename}')

        for sheet in model.sheetCategorizer.inactiveSheetsFromInactive:
            self.assert_file_equality(
                f'{inputSheetDir}inactive/{sheet.filename}',
                f'{outputSheetDir}inactive/{sheet.filename}')

        for sheet in model.sheetCategorizer.inactiveSheetsFromActive:
            self.assert_file_equality(
                f'{taggedSheetDir}{sheet.filename}',
                f'{outputSheetDir}inactive/{sheet.filename}')

        def checkObsoleteSheets(relevantNextSheetDir, relevantSheets):
            for sheet in relevantSheets:
                obsoleteDir = f'{outputSheetDir}obsolete/'
                if os.path.exists(f'{relevantNextSheetDir}{sheet.filename}'):
                    # replaced
                    self.assert_file_equality(
                        f'{taggedSheetDir}{sheet.filename}',
                        f'{obsoleteDir}replaced/{sheet.filename}')
                    self.assertTrue(os.path.exists(
                        f'{generatedSheetDir}{sheet.filename[:-4]}.jpg'),
                        f'new empty sheet {sheet.filename[:-4]}.jpg missing')
                    self.assertTrue(os.path.exists(
                        f'{outputSheetDir}active/{sheet.filename}'),
                        f'output for replaced sheet {sheet.filename} missing')
                    emptySheet = sheets.ProductSheet()
                    emptySheet.load(f'{outputSheetDir}active/{sheet.filename}')
                    self.assertTrue(len(emptySheet.emptyDataBoxes()) ==
                            sheets.ProductSheet.maxQuantity(),
                            'new replacing sheet is not empty')

                else:
                    # removed
                    self.assert_file_equality(
                        f'{taggedSheetDir}{sheet.filename}',
                        f'{obsoleteDir}removed/{sheet.filename}')
                    removedSheet = sheets.ProductSheet()
                    removedSheet.load(f'{taggedSheetDir}{sheet.filename}')

        checkObsoleteSheets(f'{nextSheetDir}active/',
                model.sheetCategorizer.obsoleteSheetsFromActive)
        checkObsoleteSheets(f'{nextSheetDir}inactive/',
                model.sheetCategorizer.obsoleteSheetsFromInactive)

        for sheet in model.sheetCategorizer.sheets:
            if sheet.newState in ['active', 'missing']:
                self.assert_file_equality(
                    f'{outputSheetDir}active/{sheet.filename}',
                    f'{nextSheetDir}active/{sheet.filename}')
            elif sheet.newState == 'inactive':
                self.assert_file_equality(
                    f'{outputSheetDir}inactive/{sheet.filename}',
                    f'{nextSheetDir}inactive/{sheet.filename}')
            else:
                assert(sheet.newState == 'obsolete')

    def check_missing_sheets(self, model):
        """
        Check products with missing sheets
        """
        self.logger.info('Check missing sheets')

        # Other sheets of a product with missing sheets should not change, but
        # for obsoleting full ones or inactivating if the product is sold out
        for missingSheet in model.sheetCategorizer.sheets:
            if missingSheet.newState != 'missing':
                continue
            product = model.db.products[missingSheet.productId()]
            soldOut = (product.inventoryQuantity or product.expectedQuantity) <= 0
            for s in model.sheetCategorizer.sheets:
                if missingSheet.productId() != s.productId():
                    continue
                if soldOut:
                    validTransitions = [('active', 'missing'),
                            ('active', 'obsolete'),
                            ('active', 'inactive')]
                    assert (s.previousState, s.newState) in validTransitions \
                            or s.newState == s.previousState, \
                        f'''{s.filename} changed from {s.previousState} to
                        {s.newState}, but the product is sold out and has
                        missing sheets'''
                else:
                    validTransitions = [('active', 'missing'),
                            ('active', 'obsolete')]
                    assert (s.previousState, s.newState) in validTransitions \
                            or s.newState == s.previousState, \
                        f'''{s.filename} changed from {s.previousState} to
                        {s.newState}, but the product is sold out and has
                        missing sheets'''

    def check_output_matches_template(self, model, modifiedProductIds,
            modifiedMemberIds):
        """
        Compare output files to template, excluding modified products / members.

        :param model: model after initializing sheets and saving them
        :type model: :class: `tagtrail_account.Model`
        :param modifiedProductIds: ids of products that were modified before
            running tagtrail_account on the template and should therefore not be
            compared to template output
        :type  modifiedProductIds: list of str
        :param modifiedMemberIds: ids of members that were modified before
            running tagtrail_account on the template and should therefore not be
            compared to template output
        :type  modifiedMemberIds: list of str
        """
        self.logger.info(f'Check output matches template')
        testNextSheetDir = f'{self.testNextDir}0_input/sheets/'
        testOutputSheetDir = f'{self.testAccountDir}5_output/sheets/'
        templateOutputSheetDir = f'{self.templateAccountDir}5_output/sheets/'
        self.check_sheets_in_dir(f'{templateOutputSheetDir}active/',
                f'{testOutputSheetDir}active/', modifiedProductIds)
        self.check_sheets_in_dir(f'{templateOutputSheetDir}inactive/',
                f'{testOutputSheetDir}inactive/', modifiedProductIds)

        templateNextSheetDir = f'{self.templateNextDir}0_input/sheets/'
        self.check_sheets_in_dir(f'{templateNextSheetDir}active/',
                f'{testNextSheetDir}/active/', modifiedProductIds)
        self.check_sheets_in_dir(f'{templateNextSheetDir}inactive/',
                f'{testNextSheetDir}/inactive/', modifiedProductIds)
        self.check_bills_in_dir(
                f'{self.templateAccountDir}3_bills/to_be_sent/',
                f'{self.testAccountDir}/3_bills/to_be_sent/',
                modifiedMemberIds)

        if modifiedProductIds == [] and modifiedMemberIds == []:
            self.assert_file_equality(
                f'{self.testAccountDir}4_gnucash/transactions.csv',
                f'{self.templateAccountDir}4_gnucash/transactions.csv')

        if modifiedMemberIds == []:
            self.assert_file_equality(
                f'{self.testNextDir}0_input/members.tsv',
                f'{self.templateNextDir}0_input/members.tsv')

        if modifiedProductIds == []:
            self.assert_file_equality(
                f'{self.testNextDir}0_input/products.csv',
                f'{self.templateNextDir}0_input/products.csv')

    def check_members_tsv(self, model):
        """
        Check invariants on next/0_input/members.tsv
        """
        self.logger.info(f'Check members.tsv')
        inputMembers = model.db.readCsv(
                f'{self.testAccountDir}0_input/members.tsv',
                database.MemberDict)
        nextMembers = model.db.readCsv(
                f'{self.testNextDir}0_input/members.tsv', database.MemberDict)
        for memberId in model.db.members:
            self.assertTrue(memberId in inputMembers)
            self.assertTrue(memberId in nextMembers)
            self.assertEqual(nextMembers.accountingDate, self.testDate)
            self.assertEqual(inputMembers[memberId].name,
                    nextMembers[memberId].name)
            self.assertEqual(inputMembers[memberId].emails,
                    nextMembers[memberId].emails)
            bill = model.db.readCsv(
                    f'{self.testAccountDir}/3_bills/to_be_sent/{memberId}.csv',
                    database.Bill)
            self.assertEqual(inputMembers[memberId].balance,
                    bill.previousBalance)
            self.assertEqual(nextMembers[memberId].balance,
                    bill.currentBalance)

    def check_products_csv(self, model):
        """
        Check invariants on next/0_input/products.csv
        """
        self.logger.info(f'Check products.csv')
        inputProducts = model.db.readCsv(
                f'{self.testAccountDir}0_input/products.csv',
                database.ProductDict)
        outputProducts = model.db.readCsv(
                f'{self.testAccountDir}5_output/products.csv',
                database.ProductDict)
        nextProducts = model.db.readCsv(
                f'{self.testNextDir}0_input/products.csv',
                database.ProductDict)
        for productId in inputProducts:
            self.assertTrue(productId in outputProducts)
            self.assertTrue(productId in nextProducts)
            outputProduct = outputProducts[productId]
            nextProduct = nextProducts[productId]

            self.assertEqual(nextProduct.soldQuantity, 0,
                f'failed to reset soldQuantity to 0 for {productId}')
            self.assertEqual(
                    outputProduct.inventoryQuantity
                    if outputProduct.inventoryQuantity is not None else
                    outputProduct.expectedQuantity,
                    nextProduct.previousQuantity +
                    nextProduct.addedQuantity)
            self.assertEqual(inputProducts[productId].addedQuantity,
                    outputProduct.addedQuantity)
            self.assertEqual(outputProduct.addedQuantity,
                    nextProduct.addedQuantity)
            if 0 < outputProduct.soldQuantity:
                self.assertNotEqual([],
                        [s.filename for s in
                            model.sheetCategorizer.scannedSheets.values()
                            if s.productId() == productId],
                        f'no scanned sheets exist for {productId}, but '
                        'soldQuantity != 0'
                        )

    def check_transactions(self, model):
        """
        Check the money transfers add up.
        """
        self.logger.info(f'Check transactions')
        (marginTransactions, merchandiseTransactions,
                paymentTransactions, inventoryDifferenceTransactions
                ) = self.load_transactions_csv(model)
        correctionTransactions = model.db.readCsv(
                f'{self.testAccountDir}0_input/correctionTransactions.csv',
                database.CorrectionTransactionDict)

        inputTotalMemberBalance = sum([member.balance
            for member in model.db.readCsv(
                f'{self.testAccountDir}0_input/members.tsv',
                database.MemberDict).values()])
        nextTotalMemberBalance = sum([member.balance
            for member in model.db.readCsv(
                f'{self.testNextDir}0_input/members.tsv',
                database.MemberDict).values()])

        # total money transfer must add up
        balanceDifference = nextTotalMemberBalance - inputTotalMemberBalance
        totalMoneyPaid = ( sum(paymentTransactions.values())
               + sum([t.amount for t in correctionTransactions.values()])
               - sum(marginTransactions.values())
               - sum(merchandiseTransactions.values()) )
        self.assertLess(abs(balanceDifference - totalMoneyPaid), 0.1,
            f'total money paid in all transactions ({totalMoneyPaid}) must add '
            f'up to total balance difference ({balanceDifference})')

        # value sold per product should be equivalent to billed sum
        for productId, product in model.db.products.items():
            # actual price might be different from product.grossSalesPrice, as
            # sheets are not necessarily replaced when price in products.csv
            # changes
            sheets = [sheet for sheet in model.sheetCategorizer.sheets if
                    sheet.productId() == productId
                    and sheet.previousState == 'active']
            actualProductPrice = (product.grossSalesPrice() if len(sheets) == 0
                    else sheets[0].grossSalesPrice)

            sumBilled = 0
            for memberId in model.db.members:
                bill = model.db.readCsv(
                        f'{self.testAccountDir}/3_bills/to_be_sent/{memberId}.csv',
                        database.Bill)
                for billPosition in bill.values():
                    if billPosition.id == productId:
                        sumBilled += billPosition.totalGrossSalesPrice()
            expectedTotal = product.soldQuantity * actualProductPrice
            self.assertLess(abs(sumBilled - expectedTotal), 0.01,
                        f'billed sum for {productId} differs from expected'
                        f'total: {sumBilled} != {expectedTotal}')

        # if inventoryQuantity and expectedQuantity of a product differ, price
        # difference should be found in inventoryDifferenceTransactions
        for product in model.db.products.values():
            quantityDifference = (0 if product.inventoryQuantity is None else
                    product.expectedQuantity - product.inventoryQuantity)
            if quantityDifference == 0:
                self.assertNotIn(product.id, inventoryDifferenceTransactions)
            else:
                self.assertIn(product.id, inventoryDifferenceTransactions)
                inventoryDifference = inventoryDifferenceTransactions[product.id]
                calculatedDifference = product.grossSalesPrice() * quantityDifference
                self.assertLess(abs(inventoryDifference - calculatedDifference), 0.01,
                    f'unexpected inventoryQuantityDifference for {product.id}: '
                    f'{inventoryDifference} != {calculatedDifference}')

    def load_accounts_csv(self):
        exportedAccounts = set()
        with open(f'{self.testAccountDir}4_gnucash/accounts.csv', newline='',
                encoding='utf-8') as csvfile:
            reader = csv.reader(csvfile, delimiter=';', quotechar='"')
            for row in reader:
                exportedAccounts.add(row[2])
        return exportedAccounts

    def load_transactions_csv(self, model):
        marginTransactions = {}
        merchandiseTransactions = {}
        paymentTransactions = {}
        inventoryDifferenceTransactions = {}
        with open(f'{self.testAccountDir}4_gnucash/transactions.csv', newline='',
                encoding='utf-8') as csvfile:
            reader = csv.reader(csvfile, delimiter=';', quotechar='"')
            for idx, row in enumerate(reader):
                if idx == 0:
                    self.assertEqual(row, ['Date', 'Description', 'Account',
                        'Withdrawal', 'Transfer Account'])
                    continue

                if row[4] == self.config.get('tagtrail_account',
                    'inventory_difference_account'):
                    productId = row[1].split(':')[0]
                    if productId not in inventoryDifferenceTransactions:
                        inventoryDifferenceTransactions[productId] = Decimal("0")
                    inventoryDifferenceTransactions[productId] += Decimal(row[3])
                elif row[2] == self.config.get('tagtrail_account',
                        'margin_account'):
                    self.assertNotIn(row[4], marginTransactions)
                    marginTransactions[row[4]] = Decimal(row[3])
                    self.assertEqual(row[0], str(self.testDate))
                    self.assertIn(row[4], model.db.members)
                elif row[2] == self.config.get('tagtrail_account',
                        'merchandise_value_account'):
                    self.assertNotIn(row[4], merchandiseTransactions)
                    merchandiseTransactions[row[4]] = Decimal(row[3])
                    self.assertEqual(row[0], str(self.testDate))
                    self.assertIn(row[4], model.db.members)
                elif row[2] in model.db.members:
                    if row[2] not in paymentTransactions:
                        paymentTransactions[row[2]] = Decimal("0")
                    paymentTransactions[row[2]] += Decimal(row[3])
                    self.assertEqual(row[4], self.config.get(
                        'tagtrail_bankimport', 'checking_account'))
                else:
                    self.assertFalse(True,
                            f'invalid account {row[2]} for transaction {row}')

        return (marginTransactions, merchandiseTransactions,
                paymentTransactions, inventoryDifferenceTransactions)

    def test_unmodified(self):
        """
        tagtrail_account should create the expected output on unmodified template
        """
        model = tagtrail_account.Model(self.testRootDir, self.testAccountDir,
                self.testNextDir, self.testDate, False)
        model.loadAccountData()
        model.save()
        self.check_output(model)

    def test_sheet_idempotence(self):
        """
        invoking tagtrail_account multiple times on the same folder should not
        change sheet state
        """
        # first, test idempotence of an accounted model
        model1 = tagtrail_account.Model(self.testRootDir, self.testAccountDir,
                self.testNextDir, self.testDate, False)
        model1.loadAccountData()

        model2 = tagtrail_account.Model(self.testRootDir, self.testAccountDir,
                self.testNextDir, self.testDate, False)
        model2.loadAccountData()

        self.assertEqual(
                sorted(map(lambda s: (s.name,
                    s.previousState if s.previousState else 'None'),
                    model1.sheetCategorizer.sheets)),
                sorted(map(lambda s: (s.name,
                    s.previousState if s.previousState else 'None'),
                    model2.sheetCategorizer.sheets)),
                'Sheet idempotence violated after reload')
        self.assertEqual(
                sorted(map(lambda s: (s.name, s.newState),
                    model1.sheetCategorizer.sheets)),
                sorted(map(lambda s: (s.name, s.newState),
                    model2.sheetCategorizer.sheets)),
                'Sheet idempotence violated after reload')

    def test_account_after_account(self):
        """
        invoking tagtrail_account with no sheets changed should leave all
        sheets in place (active remain active, inactive inactive)
        """
        helpers.recreateDir(self.tmpDir)
        shutil.copytree(f'tests/data/account_next_{self.templateName}',
                f'{self.testRootDir}')
        helpers.recreateDir(f'{self.testRootDir}3_bills')
        helpers.recreateDir(f'{self.testRootDir}5_output/sheets')
        self.config = database.Database(f'{self.testRootDir}0_input/').config

        # copy scanned sheets from active sheets, but delete
        # those which have been missing during original accounting;
        # they should not appear during this test
        shutil.copytree(f'{self.testRootDir}0_input/sheets/active/',
                f'{self.testRootDir}/2_taggedProductSheets/')
        expectedMissingSheets = []
        for (root, _, filenames) in os.walk(
                f'tests/data/account_{self.templateName}/0_input/sheets/active/'):
            for filename in filenames:
                if not os.path.exists(
                        f'tests/data/account_{self.templateName}/2_taggedProductSheets/{filename}'):
                    assert(os.path.exists(f'{self.testRootDir}2_taggedProductSheets/{filename}'))
                    os.remove(f'{self.testRootDir}2_taggedProductSheets/{filename}')
                    expectedMissingSheets.append(filename)

        os.mkdir(f'{self.testRootDir}4_gnucash/')
        shutil.copy(f'{self.templateRootDir}5_output/unprocessed_Transactions_2020-01-02_2021-03-31.csv',
                f'{self.testRootDir}5_output/unprocessed_Transactions_2021-04-01_2021-03-31.csv')
        shutil.copy(f'{self.templateRootDir}4_gnucash/transactions.csv',
                f'{self.testRootDir}4_gnucash/transactions.csv')

        self.check_category_idempotence(expectedMissingSheets)

    def test_account_after_gen(self):
        """
        invoking tagtrail_account with no sheets changed should leave all
        sheets in place (active remain active, inactive inactive)
        """
        helpers.recreateDir(self.tmpDir)
        shutil.copytree(f'tests/data/gen_next_{self.templateName}',
                f'{self.testRootDir}')
        helpers.recreateDir(f'{self.testRootDir}3_bills')
        helpers.recreateDir(f'{self.testRootDir}5_output/sheets')
        self.config = database.Database(f'{self.testRootDir}0_input/').config

        # no sheets should be missing, allowRemoval should have been set when
        # running tagtrail_gen
        expectedMissingSheets = []
        shutil.copytree(f'{self.testRootDir}0_input/sheets/active/',
                f'{self.testRootDir}/2_taggedProductSheets/')

        os.mkdir(f'{self.testRootDir}4_gnucash/')
        shutil.copy(f'{self.templateRootDir}5_output/unprocessed_Transactions_2020-01-02_2021-03-31.csv',
                f'{self.testRootDir}5_output/unprocessed_Transactions_2020-01-02_2021-03-31.csv')
        shutil.copy(f'{self.templateRootDir}4_gnucash/transactions.csv',
                f'{self.testRootDir}4_gnucash/transactions.csv')

        self.check_category_idempotence(expectedMissingSheets)

    def check_category_idempotence(self, expectedMissingSheets):
        model = tagtrail_account.Model(self.testRootDir, self.testAccountDir,
                self.testNextDir, self.testDate, False)
        model.loadAccountData()

        def sheetSetToList(s):
            return [sheet.filename for sheet in s]

        self.assertEqual([],
                sheetSetToList(model.sheetCategorizer.activeSheetsToBePrinted),
                'Incorrectly need to print sheets on second run')
        self.assertEqual(set(expectedMissingSheets),
                set(sheetSetToList(model.sheetCategorizer.missingSheets)),
                'Incorrectly found missing sheets on second run')
        self.assertEqual([],
                sheetSetToList(model.sheetCategorizer.activeSheetsFromInactive),
                'Incorrectly activated inactive sheets on second run')
        self.assertEqual([],
                sheetSetToList(model.sheetCategorizer.inactiveSheetsFromActive),
                'Incorrectly deactivated sheets on second run' +
                '- forgot allowRemoval on template generation?')
        self.assertEqual([],
                sheetSetToList(model.sheetCategorizer.obsoleteSheetsFromActive),
                'Incorrectly removed active sheets on second run' +
                '- forgot allowRemoval on template generation?')
        self.assertEqual([],
                sheetSetToList(model.sheetCategorizer.obsoleteSheetsFromInactive),
                'Incorrectly removed inactive sheets on second run' +
                '- forgot allowRemoval on template generation?')

    def test_known_product_missing(self):
        """
        tagtrail_account should abort if a product with known sheets is missing
        in database
        """
        db = database.Database(f'{self.testRootDir}0_input/')

        testProductId = None
        for (root, _, filenames) in (
                *os.walk(f'{self.testRootDir}0_input/sheets/active/'),
                *os.walk(f'{self.testRootDir}0_input/sheets/inactive/')):
            for filename in filenames:
                pId = sheets.ProductSheet.productId_from_filename(filename)
                if (pId in db.products):
                    testProductId = pId
                    break
        assert(testProductId is not None)

        removedTestProduct = False
        with open(f'{self.templateRootDir}0_input/products.csv', "r") as fin:
            with open(f'{self.testRootDir}0_input/products.csv', "w") as fout:
                for line in fin:
                    description = line.split(';')[0]
                    if slugify.slugify(description) != testProductId:
                        fout.write(line)
                    else:
                        removedTestProduct = True
        assert(removedTestProduct)

        model = tagtrail_account.Model(self.testRootDir, self.testAccountDir,
                self.testNextDir, self.testDate, False)
        self.assertRaises(ValueError, model.loadAccountData)

    def test_product_sheets_missing(self):
        """
        tagtrail_account should abort if a product in database has no sheets
        """
        db = database.Database(f'{self.testRootDir}0_input/')

        testProductId = None
        for (root, _, filenames) in (
                *os.walk(f'{self.testRootDir}0_input/sheets/active/'),
                *os.walk(f'{self.testRootDir}0_input/sheets/inactive/')):
            for filename in filenames:
                pId = sheets.ProductSheet.productId_from_filename(filename)
                if testProductId is None:
                    if (pId in db.products and
                            db.products[pId].expectedQuantity >= 0):
                        testProductId = pId
                if testProductId == pId:
                    os.remove(root+filename)
        assert(testProductId is not None)
        assert(db.products[testProductId].expectedQuantity >= 0)

        model = tagtrail_account.Model(self.testRootDir, self.testAccountDir,
                self.testNextDir, self.testDate, False)
        self.assertRaises(ValueError, model.loadAccountData)

    def test_duplicate_sheet(self):
        """
        tagtrail_account should abort if a product sheet exists twice
        """
        activeSheetDir = f'{self.testRootDir}0_input/sheets/active/'
        inactiveSheetDir = f'{self.testRootDir}0_input/sheets/inactive/'
        for filename in os.listdir(activeSheetDir):
            shutil.copy(activeSheetDir+filename, inactiveSheetDir+filename)
            break
        model = tagtrail_account.Model(self.testRootDir, self.testAccountDir,
                self.testNextDir, self.testDate, False)
        self.assertRaises(ValueError, model.loadAccountData)

    def test_missing_scan(self):
        """
        If a scan is missing, it should be shown to the user accordingly
        """
        # find a testProduct which has been active and scanned
        activeSheetDir = f'{self.testRootDir}0_input/sheets/active/'
        taggedSheetDir = f'{self.testRootDir}2_taggedProductSheets/'
        testProductId = None
        for filename in os.listdir(activeSheetDir):
            if (os.path.exists(taggedSheetDir + filename)):
                testProductId = sheets.ProductSheet.productId_from_filename(
                        filename)
                break
        assert(testProductId is not None)

        # remove scans of testProduct
        expectedMissingScans = []
        for filename in os.listdir(activeSheetDir):
            if (sheets.ProductSheet.productId_from_filename(filename) ==
                    testProductId):
                if os.path.exists(taggedSheetDir + filename):
                    os.remove(taggedSheetDir + filename)
                expectedMissingScans.append(filename)
        assert(expectedMissingScans != [])

        try:
            model = tagtrail_account.Model(self.testRootDir, self.testAccountDir,
                    self.testNextDir, self.testDate, False)
        except ValueError as e:
            assert(str(e).startswith('Following sheets are missing'))

    def test_full_product_sheet(self):
        """
        If a sheet is full, it should be shown to user as obsolete/removed
        """
        activeSheetDir = f'{self.testRootDir}0_input/sheets/active/'
        taggedSheetDir = f'{self.testRootDir}2_taggedProductSheets/'
        model = tagtrail_account.Model(self.testRootDir, self.testAccountDir,
                self.testNextDir, self.testDate, False)
        (testProduct, _) = self.create_active_test_product(model.db)
        sheet = self.generateProductSheet(model.db.config, testProduct, 4)
        sheet.store(activeSheetDir)

        memberIds = [memberId for memberId in model.db.members]
        tagsPerMember = {memberId: 0 for memberId in memberIds}
        expectedFullSheets = []
        for filename in os.listdir(activeSheetDir):
            if (sheets.ProductSheet.productId_from_filename(filename) ==
                    testProduct.id):
                sheet = sheets.ProductSheet()
                sheet.load(f'{activeSheetDir}{filename}')
                # add some tags to active input sheet (should not be acounted)
                self.add_tags_to_product_sheet(sheet, memberIds,
                        sheets.ProductSheet.maxQuantity() / 3)
                sheet.store(activeSheetDir)

                # add remaining tags to scanned product sheet, these should be
                # included in current accounting
                newTagsPerMember = self.add_tags_to_product_sheet(sheet,
                        memberIds, sheets.ProductSheet.maxQuantity())
                assert(sheet.isFull())
                sheet.store(taggedSheetDir)
                expectedFullSheets.append(filename)
                for memberId in memberIds:
                    tagsPerMember[memberId] += newTagsPerMember[memberId]

        # make sure product will not be sold out after accounting
        testProduct.addedQuantity = (5
                + len(expectedFullSheets) * sheets.ProductSheet.maxQuantity()
                - testProduct.previousQuantity)

        model.loadAccountData()
        model.save()
        self.check_output(model, modifiedProductIds = [testProduct.id],
                modifiedMemberIds = [memberId
                    for memberId, numTags in tagsPerMember.items()
                    if numTags > 0])

        # scans should be categorized 'remove'
        for expectedFullSheet in expectedFullSheets:
            self.assertIn(expectedFullSheet,
                    [s.filename for s in model.sheetCategorizer.sheets
                        if s.newState == 'obsolete'])

        self.assertEqual(model.db.products[testProduct.id].soldQuantity,
                sum(tagsPerMember.values()))
        for memberId, numTags in tagsPerMember.items():
            if numTags == 0:
                self.assertNotIn(testProduct.id, model.bills[memberId])
            else:
                self.assertEqual(model.bills[memberId][testProduct.id].numTags,
                        numTags)

    def test_product_sold_out(self):
        """
        If a product is sold out, all its sheets should become inactive
        """
        model = tagtrail_account.Model(self.testRootDir, self.testAccountDir,
                self.testNextDir, self.testDate, False)
        (testProduct, activeInputSheet) = self.create_active_test_product(model.db)

        # add tags to the active input sheet s.t. product is sold out
        assert(len(activeInputSheet.emptyDataBoxes()) ==
                sheets.ProductSheet.maxQuantity())
        tagsPerMember = self.add_tags_to_product_sheet(activeInputSheet,
                [memberId for memberId in model.db.members],
                testProduct.previousQuantity)
        assert(testProduct.previousQuantity ==
                sheets.ProductSheet.maxQuantity() -
                len(activeInputSheet.emptyDataBoxes()))
        activeInputSheet.store(f'{self.testRootDir}2_taggedProductSheets/')

        # add one inactive input sheet -> expected to be in category 'inactive'
        inactiveInputSheet = self.generateProductSheet(model.db.config,
                testProduct, 2)
        inactiveInputSheet.store(f'{self.testRootDir}0_input/sheets/inactive/')

        model.loadAccountData()
        model.save()
        self.check_output(model, modifiedProductIds = [testProduct.id],
                modifiedMemberIds = [memberId
                    for memberId, numTags in tagsPerMember.items()
                    if numTags > 0])
        self.assertIn(inactiveInputSheet.filename,
                [s.filename for s in
                    model.sheetCategorizer.inactiveSheetsFromInactive])
        self.assertIn(activeInputSheet.filename,
                [s.filename for s in
                    model.sheetCategorizer.inactiveSheetsFromActive])

        # check counts on output and next products.csv
        outputProduct = model.db.readCsv(
                f'{self.testAccountDir}5_output/products.csv',
                database.ProductDict)[testProduct.id]
        nextProduct = model.db.readCsv(
                f'{self.testNextDir}0_input/products.csv',
                database.ProductDict)[testProduct.id]
        self.assertEqual(outputProduct.previousQuantity,
                testProduct.previousQuantity)
        self.assertEqual(outputProduct.expectedQuantity, 0)
        self.assertEqual(outputProduct.soldQuantity, testProduct.previousQuantity)
        self.assertEqual(outputProduct.addedQuantity, 0)
        self.assertEqual(nextProduct.previousQuantity, 0)
        self.assertEqual(nextProduct.expectedQuantity, 0)
        self.assertEqual(nextProduct.soldQuantity, 0)
        self.assertEqual(nextProduct.addedQuantity, 0)

    def test_scanned_inactive_sheet_sold_out(self):
        """
        If a sheet was marked inactive (user should have taken it out), but is
        scanned again, it should be marked previousState=active,
        newState=inactive if it is sold out.
        """
        model = tagtrail_account.Model(self.testRootDir, self.testAccountDir,
                self.testNextDir, self.testDate, False)
        (testProduct, inputSheet) = self.create_inactive_test_product(model.db)

        # copy the inactive input sheet to be scanned again, add some more tags
        assert(testProduct.expectedQuantity <= 0)
        tagsPerMember = self.add_tags_to_product_sheet(inputSheet,
                [memberId for memberId in model.db.members],
                7)
        soldQuantity = sum(tagsPerMember.values())
        expectedQuantity = (testProduct.expectedQuantity - soldQuantity)
        assert(expectedQuantity < 0)
        inputSheet.store(f'{self.testRootDir}2_taggedProductSheets/')

        model.loadAccountData()
        model.save()
        self.assertIn(inputSheet.filename,
            [s.filename for s in model.sheetCategorizer.sheets if
                s.previousState == 'active' and s.newState == 'inactive'])
        try:
            self.check_output(model, modifiedProductIds = [testProduct.id],
                    modifiedMemberIds = [memberId
                        for memberId, numTags in tagsPerMember.items()
                        if numTags > 0])
        except AssertionError as e:
            assert(str(e).startswith("'dataBox0(0,0);"))

        # check counts on output and next products.csv
        outputProduct = model.db.readCsv(
                f'{self.testAccountDir}5_output/products.csv',
                database.ProductDict)[testProduct.id]
        nextProduct = model.db.readCsv(
                f'{self.testNextDir}0_input/products.csv',
                database.ProductDict)[testProduct.id]
        self.assertEqual(outputProduct.previousQuantity,
                testProduct.previousQuantity)
        self.assertEqual(outputProduct.expectedQuantity,
                expectedQuantity)
        self.assertEqual(outputProduct.soldQuantity, soldQuantity)
        self.assertEqual(outputProduct.addedQuantity, 0)
        self.assertEqual(nextProduct.previousQuantity,
                expectedQuantity)
        self.assertEqual(nextProduct.expectedQuantity,
                expectedQuantity)
        self.assertEqual(nextProduct.soldQuantity, 0)
        self.assertEqual(nextProduct.addedQuantity, 0)

    def test_scanned_inactive_sheet_in_stock(self):
        """
        If a sheet was marked inactive (user should have taken it out), but is
        scanned again, it should be marked previousState=active,
        newState=active if it is sold out.
        """
        db = database.Database(f'{self.testRootDir}0_input/')
        (testProduct, inputSheet) = self.create_inactive_test_product(db)

        # copy the inactive input sheet to be scanned again, add some tags
        tagsPerMember = self.add_tags_to_product_sheet(inputSheet,
                [memberId for memberId in db.members],
                42)
        inputSheet.store(f'{self.testRootDir}2_taggedProductSheets/')

        # add high enough quantity for product to be in stock after accounting
        # write modified products.csv
        previousQuantity = testProduct.previousQuantity
        soldQuantity = sum(tagsPerMember.values())
        addedQuantity = (-testProduct.expectedQuantity + soldQuantity + 5)
        expectedQuantity = previousQuantity - soldQuantity + addedQuantity
        assert(previousQuantity < 0)
        assert(expectedQuantity > 0)
        testProduct.addedQuantity = addedQuantity
        db.writeCsv(f'{self.testRootDir}0_input/products.csv', db.products)

        model = tagtrail_account.Model(self.testRootDir, self.testAccountDir,
                self.testNextDir, self.testDate, False)
        model.loadAccountData()
        model.save()
        self.assertIn(inputSheet.filename,
            [s.filename for s in model.sheetCategorizer.sheets if
                s.previousState == 'active' and s.newState == 'active'])
        self.check_output(model, modifiedProductIds = [testProduct.id],
                modifiedMemberIds = [memberId
                    for memberId, numTags in tagsPerMember.items()
                    if numTags > 0])

        # check counts on output and next products.csv
        outputProduct = model.db.readCsv(
                f'{self.testAccountDir}5_output/products.csv',
                database.ProductDict)[testProduct.id]
        nextProduct = model.db.readCsv(
                f'{self.testNextDir}0_input/products.csv',
                database.ProductDict)[testProduct.id]
        self.assertEqual(outputProduct.previousQuantity, previousQuantity)
        self.assertEqual(outputProduct.expectedQuantity, expectedQuantity)
        self.assertEqual(outputProduct.soldQuantity, soldQuantity)
        self.assertEqual(outputProduct.addedQuantity, addedQuantity)
        self.assertEqual(nextProduct.previousQuantity, previousQuantity -
                soldQuantity)
        self.assertEqual(nextProduct.expectedQuantity, expectedQuantity)
        self.assertEqual(nextProduct.soldQuantity, 0)
        self.assertEqual(nextProduct.addedQuantity, addedQuantity)

    def test_sheet_replacement(self):
        """
        Mark an active sheet to be replaced (if it was mistreated in some way)
        """
        model = tagtrail_account.Model(self.testRootDir, self.testAccountDir,
                self.testNextDir, self.testDate, False)
        (testProduct, inputSheet) = self.create_active_test_product(model.db)
        model.loadAccountData()
        for sheet in model.sheetCategorizer.sheets:
            if sheet.filename == inputSheet.filename:
                sheet.category = 'replace'
        model.save()
        self.check_output(model, modifiedProductIds = [testProduct.id])

    def test_negative_balance(self):
        """
        Use up all money of the richest member to get a negative balance
        """
        unmodifiedModel = tagtrail_account.Model(self.testRootDir, self.testAccountDir,
                self.testNextDir, self.testDate, False)
        unmodifiedModel.loadAccountData()

        # select the member that would be richest after unmodified accounting
        testMemberId, unmodifiedBill = sorted(unmodifiedModel.bills.items(),
                key = lambda elem: elem[1].currentBalance)[-1]

        # sell products to testMember until balance gets negative
        taggedSheetDir = f'{self.testRootDir}2_taggedProductSheets/'
        additionalSoldValue = 0
        modifiedProductIds = []
        for filename in os.listdir(taggedSheetDir):
            if not filename.endswith('.csv'):
                continue
            if os.path.exists(
                    f'{self.testRootDir}0_input/sheets/inactive/{filename}'):
                continue
            if additionalSoldValue > unmodifiedBill.currentBalance:
                break

            sheet = sheets.ProductSheet()
            sheet.load(f'{taggedSheetDir}{filename}')
            numEmptyTags = len(sheet.emptyDataBoxes())
            # fill product sheet with tags of testMember
            self.add_tags_to_product_sheet(sheet, [testMemberId],
                    sheets.ProductSheet.maxQuantity())
            assert(len(sheet.emptyDataBoxes()) == 0)
            additionalSoldValue += numEmptyTags * sheet.grossSalesPrice
            modifiedProductIds.append(sheet.productId())
            sheet.store(taggedSheetDir)

        # set balance to a fixed value with a correction transaction
        # (corection will be negative if we didn't manage to make the member's
        # balance negative enough, else positive if we were overshooting too
        # much)
        expectedBalance = Decimal("-100.25")
        correctionTransactions = unmodifiedModel.db.readCsv(
                f'{self.testRootDir}0_input/correctionTransactions.csv',
                database.CorrectionTransactionDict)
        correctionTransactions[testMemberId] = database.CorrectionTransaction(
                testMemberId,
                expectedBalance - unmodifiedBill.currentBalance + additionalSoldValue,
                'Get a negative balance!')
        unmodifiedModel.db.writeCsv(f'{self.testRootDir}0_input/correctionTransactions.csv',
                correctionTransactions)

        # check outcome
        model = tagtrail_account.Model(self.testRootDir, self.testAccountDir,
                self.testNextDir, self.testDate, False)
        model.loadAccountData()
        model.save()
        self.check_output(model, modifiedProductIds = modifiedProductIds,
                modifiedMemberIds = [testMemberId])
        self.assertEqual(model.bills[testMemberId].currentBalance,
                expectedBalance)

    def test_adding_member(self):
        """
        Adding a new member should give him a balance of 0 and the necessary
        gnucash account / transaction files
        """
        db = database.Database(f'{self.testRootDir}0_input/')
        testMember = database.Member('testMember', 'Test Member',
                ['test1@gmail.com', 'test2@gmail.com'], Decimal("0.0"))
        db.members[testMember.id] = testMember
        db.writeCsv(f'{self.testRootDir}0_input/members.tsv', db.members)

        model = tagtrail_account.Model(self.testRootDir, self.testAccountDir,
                self.testNextDir, self.testDate, False)
        model.loadAccountData()
        model.save()
        self.check_output(model, modifiedMemberIds = [testMember.id])
        self.assertEqual(model.bills[testMember.id].currentBalance,
                Decimal("0"))

    def test_removing_active_member(self):
        """
        Removing a member with new tags should raise an error
        """
        # search a member with at least one new tag, remove from members.tsv
        model = tagtrail_account.Model(self.testRootDir, self.testAccountDir,
                self.testNextDir, self.testDate, False)
        model.loadAccountData()
        testMemberId = None
        for memberId in model.db.members:
            if len(model.bills[memberId]) != 0:
                testMemberId = memberId
                break
        assert(testMemberId != None)
        model.db.members.pop(testMemberId)
        model.db.writeCsv(f'{self.testRootDir}0_input/members.tsv',
                model.db.members)

        model = tagtrail_account.Model(self.testRootDir, self.testAccountDir,
                self.testNextDir, self.testDate, False)
        assert(testMemberId not in model.db.members)
        self.assertRaises(ValueError, model.loadAccountData)

    def test_removing_inactive_member(self):
        """
        Removing a member without new tags should work
        """
        # search a member without any new tags, remove from members.tsv
        model = tagtrail_account.Model(self.testRootDir, self.testAccountDir,
                self.testNextDir, self.testDate, False)
        model.loadAccountData()
        testMemberId = None
        for memberId in model.db.members:
            if len(model.bills[memberId]) == 0:
                testMemberId = memberId
                break
        assert(testMemberId != None)
        model.db.members.pop(testMemberId)
        model.db.writeCsv(f'{self.testRootDir}0_input/members.tsv',
                model.db.members)

        model = tagtrail_account.Model(self.testRootDir, self.testAccountDir,
                self.testNextDir, self.testDate, False)
        assert(testMemberId not in model.db.members)
        model.loadAccountData()
        model.save()
        self.check_output(model, modifiedMemberIds = [testMemberId])

    def test_add_multiple_corrections_per_member(self):
        """
        Only one correction transaction per member allowed, expecting error
        """
        model = tagtrail_account.Model(self.testRootDir, self.testAccountDir,
                self.testNextDir, self.testDate, False)
        model.loadAccountData()
        assert(len(model.correctionTransactions) != 0)

        lines = []
        with open(f'{self.testRootDir}0_input/correctionTransactions.csv',
                "r") as fin:
            lines = [line for line in fin]

        with open(f'{self.testRootDir}0_input/correctionTransactions.csv',
                "w") as fout:
            for line in lines:
                fout.write(line)
            fout.write(lines[-1])

        self.assertRaises(ValueError, model.loadAccountData)

    def test_adding_payment(self):
        """
        Test adding a payment works
        """
        # create and add a new member
        initialBalance = Decimal("123.15")
        db = database.Database(f'{self.testRootDir}0_input/')
        testMember = database.Member('testMember', 'Test Member',
                ['test1@gmail.com', 'test2@gmail.com'], initialBalance)
        db.members[testMember.id] = testMember
        db.writeCsv(f'{self.testRootDir}0_input/members.tsv', db.members)

        # add some payment
        paymentAmount = Decimal("222.22")
        transactionsfilepath = f'{self.testRootDir}4_gnucash/transactions.csv'
        inputTransactions = db.readCsv(transactionsfilepath,
                database.GnucashTransactionList)
        inputTransactions.append(database.GnucashTransaction(
            'Test payment',
            paymentAmount,
            testMember.id,
            db.config.get('tagtrail_bankimport', 'checking_account'),
            self.testDate))
        db.writeCsv(transactionsfilepath, inputTransactions)

        model = tagtrail_account.Model(self.testRootDir, self.testAccountDir,
                self.testNextDir, self.testDate, False)
        model.loadAccountData()
        model.save()

        # checks if payment appears in output transactions and the members bill
        self.check_output(model, modifiedMemberIds = [testMember.id])

        self.assertEqual(model.bills[testMember.id].previousBalance,
                initialBalance)
        self.assertEqual(model.bills[testMember.id].currentBalance,
                initialBalance + paymentAmount)

    def test_change_already_accounted_tag(self):
        """
        If a tag on an input sheet is changed, an error should be raised
        """
        model = tagtrail_account.Model(self.testRootDir, self.testAccountDir,
                self.testNextDir, self.testDate, False)
        (_, activeInputSheet) = self.create_active_test_product(model.db)
        self.add_tags_to_product_sheet(activeInputSheet,
                [memberId for memberId in model.db.members],
                10)
        activeInputSheet.store(f'{self.testRootDir}0_input/sheets/active/')

        # change some tag
        testBox = activeInputSheet.boxByName('dataBox1(0,1)')
        assert(testBox.text != '')
        for memberId in model.db.members:
            if memberId != testBox.text:
                testBox.text = memberId
                break
        activeInputSheet.store(f'{self.testRootDir}2_taggedProductSheets/')

        self.assertRaises(ValueError, model.loadAccountData)

    def test_inconsistent_bill_vs_sale_total(self):
        """
        tagtrail_account should do a basic check if the amount billed to all
        members and the total value of a product sold should be equal.

        Manipulating a bill before saving is expected to raise an error.
        """
        model = tagtrail_account.Model(self.testRootDir, self.testAccountDir,
                self.testNextDir, self.testDate, False)
        model.loadAccountData()

        billChanged = False
        for bill in model.bills.values():
            if len(bill) != 0:
                previousPrice = bill.totalGrossSalesPrice()
                bill.popitem()
                assert(previousPrice != bill.totalGrossSalesPrice())
                billChanged = True
                break
        assert(billChanged)
        self.assertRaises(ValueError, model.save)

    def test_inventory_date(self):
        """
        Inventory date must be the same as accounting date -> error expected
        otherwise
        """
        db = database.Database(f'{self.testRootDir}0_input/')
        productsFilePath = f'{self.testRootDir}0_input/products.csv'
        inputProducts = db.readCsv(productsFilePath, database.ProductDict)
        for product in inputProducts.values():
            product.inventoryQuantity = product.expectedQuantity

        # test inventory with correct date - should be able to load data
        inputProducts.inventoryQuantityDate = self.testDate
        db.writeCsv(productsFilePath, inputProducts)

        model = tagtrail_account.Model(self.testRootDir, self.testAccountDir,
                self.testNextDir, self.testDate, False)
        model.loadAccountData()

        # test inventory with another date - error expected
        inputProducts.inventoryQuantityDate = (
                self.testDate - datetime.timedelta(days = 3))
        db.writeCsv(productsFilePath, inputProducts)

        self.assertRaises(ValueError, lambda: tagtrail_account.Model(
            self.testRootDir, self.testAccountDir, self.testNextDir,
            self.testDate, False))

    def test_partial_inventory(self):
        """
        Inventory quantity must be filled for all or none of the products
        """
        modelConstructor = lambda: tagtrail_account.Model(
            self.testRootDir, self.testAccountDir, self.testNextDir,
            self.testDate, False)

        db = database.Database(f'{self.testRootDir}0_input/')
        productsFilePath = f'{self.testRootDir}0_input/products.csv'
        inputProducts = db.readCsv(productsFilePath, database.ProductDict)

        # correct inventory date given, but inventory quantities missing
        inputProducts.inventoryQuantityDate = self.testDate
        db.writeCsv(productsFilePath, inputProducts)
        self.assertRaises(ValueError, modelConstructor)

        # add quantities but for one product
        missingProduct = None
        for idx, product in enumerate(inputProducts.values()):
            if idx == 0:
                product.inventoryQuantity = None
                missingProduct = product
            else:
                product.inventoryQuantity = product.expectedQuantity
        assert(missingProduct is not None)
        db.writeCsv(productsFilePath, inputProducts)
        self.assertRaises(ValueError, modelConstructor)

        # add quantities for missing product -> should work now
        missingProduct.inventoryQuantity = missingProduct.expectedQuantity
        db.writeCsv(productsFilePath, inputProducts)

        model = modelConstructor()
        model.loadAccountData()
        model.save()
        self.check_output(model,
                modifiedProductIds = [pId for pId in inputProducts.keys()])

    def test_inventory_transactions(self):
        """
        Make an inventory with differences to expected stock, check correct
        transactions are generated for accounting the differences found in
        expected vs real stock.
        """
        db = database.Database(f'{self.testRootDir}0_input/')
        productsFilePath = f'{self.testRootDir}0_input/products.csv'
        inputProducts = db.readCsv(productsFilePath, database.ProductDict)
        assert(len(inputProducts) >= 3)

        for idx, product in enumerate(inputProducts.values()):
            if idx == 0:
                # one product with a surplus found during inventory
                product.inventoryQuantity = product.expectedQuantity + 7
            elif idx == 1:
                # one product with a loss discovered during inventory
                product.inventoryQuantity = product.expectedQuantity - 2
            elif idx == 2:
                # one product where inventory revealed expected stock
                product.inventoryQuantity = product.expectedQuantity
            else:
                product.inventoryQuantity = (product.expectedQuantity +
                        random.randint(-100, 100))
        inputProducts.inventoryQuantityDate = self.testDate
        db.writeCsv(productsFilePath, inputProducts)

        model = tagtrail_account.Model(self.testRootDir, self.testAccountDir,
                self.testNextDir, self.testDate, False)
        model.loadAccountData()
        model.save()
        self.check_output(model,
                modifiedProductIds = [pId for pId in inputProducts.keys()])

    def test_update_co2_values(self):
        """
        Check if updating Co2 values from eaternity works
        """
        if self.keyringPassword is None:
            msg = '--keyringPassword not provided'
            print(f'skipping test: {msg}')
            self.skipTest(msg)

        # make sure api key for eaternity is available
        credentialsFilePath = self.config.get('general',
            'password_file_path')
        keyring = helpers.Keyring(credentialsFilePath, self.keyringPassword)
        try:
            apiKey = keyring.get_password('eaternity', 'apiKey')
        except KeyError:
            msg = f'--apiKey not provided in {credentialsFilePath}'
            print(f'skipping test: {msg}')
            self.skipTest(msg)

        # all test preconditions met

        # reset co2 values of all input products
        db = database.Database(f'{self.testRootDir}0_input/')
        inputProductsFilePath = f'{self.testRootDir}0_input/products.csv'
        inputProducts = db.readCsv(inputProductsFilePath, database.ProductDict)
        for product in inputProducts.values():
            product.gCo2e = None
        db.writeCsv(inputProductsFilePath, inputProducts)

        model = tagtrail_account.Model(self.testRootDir, self.testAccountDir,
                self.testNextDir, self.testDate, True, self.keyringPassword)
        model.loadAccountData()
        model.save()
        self.check_output(model,
                # all member bills would have changed if co2 values have been
                # updated by eaternity
                modifiedMemberIds = [mId for mId in model.db.members.keys()],
                modifiedProductIds = [pId for pId in model.db.products.keys()])

        # check all co2 values were updated
        outputProductsFilePath = f'{self.testAccountDir}5_output/products.csv'
        for product in db.readCsv(outputProductsFilePath,
                database.ProductDict).values():
            self.assertNotEqual(product.gCo2e, None,
                    f'failed to update gCo2e for {product.id}')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Test tagtrail_account')
    parser.add_argument('--pattern',
            default=None,
            help='Only run tests containing `pattern` in there id.')
    parser.add_argument('--keyringPassword',
            default=None,
            help='Password for config/credentials.cfg. '
            'If keyringPassword is missing, test_update_co2_values is '
            'omitted as it needs to retrieve an api key to access eaternity')
    parser.add_argument('--logLevel', dest='logLevel',
            help='Log level to write to console', default='INFO')
    args = parser.parse_args()
    helpers.configureLogger(logging.getLogger('tagtrail'), consoleLevel =
            logging.getLevelName(args.logLevel))

    AccountTest.keyringPassword = args.keyringPassword
    loader = unittest.TestLoader()
    completeSuite = loader.loadTestsFromTestCase(AccountTest)
    filteredSuite = unittest.TestSuite()
    for test in completeSuite:
        if args.pattern is not None and test.id().find(args.pattern) == -1:
            print(f'skip {test.id()} - {args.pattern} not contained')
        else:
            filteredSuite.addTest(test)

    runner = unittest.TextTestRunner()
    runner.run(filteredSuite)

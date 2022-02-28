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
import re
import os
import shutil
import datetime
import time
import tkinter
import traceback

from . import database
from . import helpers
from . import gui_components

class EnrichedDatabase(database.Database):

    def __init__(self,
            accountingDataPath,
            accountingDate):

        super().__init__(f'{accountingDataPath}0_input/')
        toDate = accountingDate-datetime.timedelta(days=1)
        self.accountingDataPath = accountingDataPath
        filenameDateFormat = self.config.get('postfinance_transactions',
                        'filename_date_format')
        self.inputTransactionsPath = (
                self.accountingDataPath
                + '0_input/export_transactions_'
                + helpers.DateUtility.strftime(self.previousAccountingDate,
                    filenameDateFormat)
                + '_'
                + helpers.DateUtility.strftime(toDate,
                    filenameDateFormat)
                + '.csv')
        self.unprocessedTransactionsPath = self.accountingDataPath + \
                '5_output/unprocessed_Transactions_' + \
                helpers.DateUtility.strftime(self.previousAccountingDate) + '_' + \
                helpers.DateUtility.strftime(toDate) + '.csv'
        self.paymentTransactionsPath = f'{self.accountingDataPath}4_gnucash/transactions.csv'
        if not os.path.isfile(self.inputTransactionsPath):
            raise ValueError(
                    f'Missing required file {self.inputTransactionsPath}\n')

        if not os.path.isfile(self.unprocessedTransactionsPath):
            helpers.recreateDir(f'{self.accountingDataPath}4_gnucash/', self.log)
            helpers.recreateDir(f'{self.accountingDataPath}5_output/', self.log)
            self.log.info("copy {} to {}".format(self.inputTransactionsPath, self.unprocessedTransactionsPath))
            shutil.copy(self.inputTransactionsPath, self.unprocessedTransactionsPath)

        self.postfinanceTransactions = self.loadPostfinanceTransactions(
                self.previousAccountingDate, toDate)

    def loadPostfinanceTransactions(self, fromDate, toDate):
        self.log.info(f"loading transactions from {self.unprocessedTransactionsPath}")
        loadedTransactions = self.readCsv(
                self.unprocessedTransactionsPath,
                database.PostfinanceTransactionList)
        if loadedTransactions.dateFrom != fromDate:
            raise ValueError(
                    f"'Date from'='{loadedTransactions.dateFrom}' must " + \
                    f"be the previous accounting date '{fromDate}'")
        if loadedTransactions.dateTo != toDate:
            raise ValueError(
                    f"'Date to'='{loadedTransactions.dateTo}' must " + \
                    f"be one day before the current accounting date '{toDate}'")
        for transaction in loadedTransactions:
            transaction.memberId = transaction.inferMemberId(list(sorted(self.members.keys())))
            self.log.debug(f'inferred memberId {transaction.memberId}')
        return loadedTransactions

    @property
    def previousAccountingDate(self):
        return self.members.accountingDate


class GUI(gui_components.BaseGUI):
    buttonFrameWidth=200

    def __init__(self,
            accountingDataPath,
            accountingDate):

        self.accountingDataPath = accountingDataPath
        self.accountingDate = accountingDate

        self.transactionFrame = None
        self.scrollbarY = None

        if not self.loadData():
            return

        width = self.db.config.getint('general', 'screen_width')
        width = None if width == -1 else width
        height = self.db.config.getint('general', 'screen_height')
        height = None if height == -1 else height
        super().__init__(width, height, helpers.Log())

    def populateRoot(self):
        self.root.bind("<Tab>", self.switchInputFocus)
        self.root.bind("<Return>", self.switchInputFocus)
        self.root.bind("<Up>", self.switchInputFocus)
        self.root.bind("<Down>", self.switchInputFocus)
        self.root.bind("<Left>", self.switchInputFocus)
        self.root.bind("<Right>", self.switchInputFocus)

        if self.transactionFrame is None:
            self.transactionFrame = gui_components.ScrollableFrame(self.root,
                    relief=tkinter.GROOVE)
        self.transactionFrameWidth = self.width - self.buttonFrameWidth
        self.transactionFrame.config(width = self.transactionFrameWidth,
                    height = self.height)
        self.transactionFrame.place(x=0, y=0)
        self.loadTransactions()

        buttons = []
        buttons.append(('saveAndExit', 'Save and exit', self.saveAndExit))
        buttons.append(('saveAndReload', 'Save and reload current', self.saveAndReloadDB))
        self.addButtonFrame(buttons)

    def loadTransactions(self):
        for w in self.transactionFrame.scrolledwindow.winfo_children():
            w.destroy()
        entryWidth = self.buttonFrameWidth
        possibleMemberIds = list(sorted(self.db.members.keys()))
        y = 0
        self.entries = []
        backgroundColors = ['lightgray', 'darkgray']
        for idx, transaction in enumerate(self.db.postfinanceTransactions):
            if transaction.creditAmount is None:
                continue

            backgroundColor = backgroundColors[idx % 2]
            frame = tkinter.Frame(self.transactionFrame.scrolledwindow, relief=tkinter.RIDGE,
                    background=backgroundColor, borderwidth=3)
            frame.pack(fill=tkinter.BOTH)

            label = tkinter.Message(frame,
                    text=transaction.notificationText,
                    anchor=tkinter.E,
                    background=backgroundColor,
                    width=self.transactionFrameWidth)
            label.pack(side=tkinter.RIGHT, fill=tkinter.BOTH)

            # need to update the screen to get the correct label height
            # caveat: during the update, a <Configure> event might be triggered
            # and invalidate the whole process => abort if we are outdated
            frame.update()
            if not frame.winfo_exists():
                return

            h = frame.winfo_height()

            if transaction.memberId is None:
                mostLikely = transaction.mostLikelyMemberId(possibleMemberIds)
                text = '' if mostLikely is None else mostLikely
                confidence = 0
            else:
                text = transaction.memberId
                confidence = 1
            entry = gui_components.AutocompleteEntry(text, confidence, possibleMemberIds,
                    self.switchFocus, True,
                    self.transactionFrame.scrolledwindow, frame.winfo_x(),
                    frame.winfo_y()+h, frame)
            entry.transaction = transaction
            entry.pack(side=tkinter.LEFT)
            self.entries.append(entry)
            y += h+2

        nextUnclearEntry = self.nextUnclearEntry(None)
        if not nextUnclearEntry is None:
            nextUnclearEntry.focus_set()

    def switchFocus(self, event):
        # cudos to https://www.daniweb.com/programming/software-development/code/216830/tkinter-keypress-event-python
        if event.type == '2' and event.char != event.keysym:
            # punctuation or special key, distinguish by event.keysym
            if event.keysym == "Return":
                event.widget.confidence=1
                event.widget.transaction.memberId = event.widget.text

            if event.keysym in ["Return", "Tab"]:
                nextUnclearEntry = self.nextUnclearEntry(event.widget)
                if not nextUnclearEntry is None:
                    nextUnclearEntry.focus_set()

            elif event.keysym == "Up":
                currentIndex = self.entries.index(event.widget)
                nextIndex = len(self.entries)-1 if currentIndex == 0 else currentIndex-1
                self.entries[nextIndex].focus_set()
            elif event.keysym == "Down":
                currentIndex = self.entries.index(event.widget)
                nextIndex = 0 if currentIndex == len(self.entries)-1 else currentIndex+1
                self.entries[nextIndex].focus_set()

        return event

    def nextUnclearEntry(self, selectedEntry):
        indicesOfUnclearEntries = [idx for idx, e in enumerate(self.entries) if e.confidence<1]
        if not indicesOfUnclearEntries:
            return None
        else:
            try:
                currentIndex = self.entries.index(selectedEntry)
            except ValueError:
                currentIndex = 0
            if max(indicesOfUnclearEntries) <= currentIndex:
                return self.entries[min(indicesOfUnclearEntries)]
            else:
                return self.entries[min(filter(lambda x: currentIndex < x,
                    indicesOfUnclearEntries))]

    def saveAndExit(self, event=None):
        self.save()
        self.root.destroy()

    def loadData(self):
        """
        Load data and return True if any work remains to be done, else False
        """
        self.db = EnrichedDatabase(self.accountingDataPath,
                self.accountingDate)
        paymentTransactions = [t for t in self.db.postfinanceTransactions if
                t.creditAmount is not None]
        if len(paymentTransactions) == 0:
            tkinter.messagebox.showinfo(
                'Nothing to do', 'All payment transactions have been processed')
            return False
        return True

    def saveAndReloadDB(self, event=None):
        self.save()
        self.loadData()
        self.loadTransactions()
        return "break"

    def save(self):
        if os.path.isfile(self.db.paymentTransactionsPath):
            paymentTransactions = self.db.readCsv(self.db.paymentTransactionsPath,
                    database.GnucashTransactionList)
        else:
            paymentTransactions = database.GnucashTransactionList(self.db.config)

        numberOfTransactions = len(paymentTransactions) + len(self.db.postfinanceTransactions)
        indicesToRemove = []
        for idx, pfTransaction in enumerate(self.db.postfinanceTransactions):
            self.log.debug(f'paymentTransactions = {[t.sourceAccount for t in paymentTransactions]}')
            self.log.debug(f'postfinanceTransactions = {[t.memberId for t in self.db.postfinanceTransactions]}')
            self.log.debug(f'indicesToRemove = {indicesToRemove}')
            if pfTransaction.memberId is None or \
                    not pfTransaction.memberId in self.db.members:
                continue
            self.log.debug(f'identified transaction for {pfTransaction.memberId}')
            gnucashTransaction = database.GnucashTransaction(
                pfTransaction.notificationText,
                pfTransaction.creditAmount,
                pfTransaction.memberId,
                self.db.config.get('tagtrail_bankimport', 'checking_account'),
                pfTransaction.bookingDate)
            if not gnucashTransaction in paymentTransactions:
                paymentTransactions.append(gnucashTransaction)
                indicesToRemove.append(idx)
                self.log.debug(f'marked transaction to be removed from postfinanceTransactions')
                assert(gnucashTransaction in paymentTransactions)
                assert(not gnucashTransaction in self.db.postfinanceTransactions)
            else:
                raise ValueError(f'Transaction {pfTransaction} exists in ' + \
                f'{self.db.paymentTransactionsPath} as well as ' + \
                f'{self.db.unprocessedTransactionsPath}. Remove ' + \
                f'{self.db.unprocessedTransactionsPath}, correct ' + \
                f'{self.db.inputTransactionsPath} and start ' + \
                'tagtrail_bankimport again.')
        self.db.postfinanceTransactions[:] = [transaction for idx, transaction in
                enumerate(self.db.postfinanceTransactions)
                if not idx in indicesToRemove]

        if numberOfTransactions != len(paymentTransactions) + \
                len(self.db.postfinanceTransactions):
                    raise AssertionError('numberOfTransactions is not ' + \
                            'consistent, please file a bug at ' + \
                            'https://github.com/greuters/tagtrail')

        self.db.writeCsv(self.db.paymentTransactionsPath, paymentTransactions)
        self.db.writeCsv(self.db.unprocessedTransactionsPath, self.db.postfinanceTransactions)

    def switchInputFocus(self, event):
        focused = self.root.focus_displayof()
        if not focused:
            return event
        elif isinstance(focused, gui_components.AutocompleteEntry):
            if focused.confidence == 1 and event.keysym in ('Tab', 'Return'):
                self.buttons['saveAndExit'].focus_set()
        elif event.keysym == 'Tab':
            focused.tk_focusNext().focus_set()
        else:
            return event
        return 'break'

if __name__== "__main__":
    parser = argparse.ArgumentParser(
        description='Load transactions exported from Postfinance, ' + \
                'recognize payments from members and store unprocessed ' + \
                'transactions for manual entry to GnuCash.')
    parser.add_argument('accountingDir',
            help='Top-level tagtrail directory to process, usually data/next/')
    parser.add_argument('--accountingDate',
            dest='accountingDate',
            type=helpers.DateUtility.strptime,
            default=helpers.DateUtility.todayStr(),
            help="Date of the new accounting, fmt='YYYY-mm-dd'",
            )
    args = parser.parse_args()
    GUI(args.accountingDir, args.accountingDate)

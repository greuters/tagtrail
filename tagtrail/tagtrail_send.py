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
import getpass
import argparse
from abc import ABC, abstractmethod
from string import Template
import helpers
import database
import time
import csv
import imaplib
import smtplib
import ssl
from email import encoders
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from keyrings.cryptfile.cryptfile import CryptFileKeyring

class MailSender(ABC):
    # TODO load from config
    mailUser = 'info@speichaer.ch'
    mailHost = 'mail.cyon.ch'
    smtpPort = 465
    imapPort = 993
    invoiceIban = 'CH3609000000890399940'
    liquidityThreshold = 100
    password_file_path = './config/cryptfile_pass.cfg'

    def __init__(self,
            accountingPath,
            accessCode,
            accountantName,
            testRecipient = None
            ):
        self.accessCode = accessCode
        self.log = helpers.Log(helpers.Log.LEVEL_DEBUG)
        self.billPath = accountingPath + '3_bills/'
        self.templatePath = accountingPath + '0_input/templates/'
        self.db = database.Database(f'{accountingPath}0_input/')
        self.bills = [database.Database.readCsv(
            f'{self.billPath}{member.id}.csv', database.Bill)
            for member in self.db.members.values()]

        self.emailTemplate = self.readTemplate(self.templatePath+'email.txt')
        self.invoiceAboveThresholdTemplate = self.readTemplate(
                self.templatePath+'invoice_above_threshold.txt')
        self.invoiceBelowThresholdTemplate = self.readTemplate(
                self.templatePath+'invoice_below_threshold.txt')
        self.correctionTextTemplate = self.readTemplate(
                self.templatePath+'correction.txt')

        self.accountantName = accountantName

        keyring = CryptFileKeyring()
        for attempt in range(3):
            try:
                keyring.file_path = self.password_file_path
                # this call asks the user for the keyring password in the background
                # if it is wrong, a ValueError is raised - ugly, but only
                # working solution I found so far
                self.mailPassword = keyring.get_password('tagtrail_send', self.mailUser)
                break
            except ValueError:
                print('Failed to open keyring - Wrong password?')
                keyring = CryptFileKeyring()
        else:
            raise ValueError('Failed to open keyring - run out of retries')

        if self.mailPassword is None:
            # if we made it here, the keyring is opened
            self.mailPassword = getpass.getpass(f'Password for {self.mailUser}:')
            keyring.set_password('tagtrail_send', self.mailUser,
                    self.mailPassword)

        self.testRecipient = testRecipient

    def readTemplate(self, filename):
        with open(filename, 'r', encoding='utf-8') as template_file:
            template_file_content = template_file.read()
        return Template(template_file_content)

    def sendBills(self):
        billedMembersWithoutEmails = [bill.memberId for bill in self.bills
                if self.db.members[bill.memberId].emails == []]
        if billedMembersWithoutEmails != []:
            answer = input('Bills cannot be sent to these members, ' + \
                  'as they have no email:\n' + \
                  f'{",".join(billedMembersWithoutEmails)}\n' + \
                    'Continue (yes/no)? ')
            if answer != 'yes':
                return

        for bill in self.bills:
            invoiceTextTemplate = self.invoiceAboveThresholdTemplate \
                    if self.liquidityThreshold < bill.currentBalance() else \
                    self.invoiceBelowThresholdTemplate
            correctionText = '' if bill.correctionTransaction == 0 else \
                    self.correctionTextTemplate.substitute(
                    CORRECTION_TRANSACTION=helpers.formatPrice(bill.correctionTransaction, 'CHF'),
                    CORRECTION_JUSTIFICATION=bill.correctionJustification)

            for email in self.db.members[bill.memberId].emails:
                if not self.testRecipient is None:
                    self.log.info(f'would send email to {email}, replaced by {self.testRecipient}: ')
                    email = self.testRecipient

                name = self.db.members[bill.memberId].name
                self.log.info('Sending email to {}, {}'.format(email, name))
                body = self.emailTemplate.substitute(
                            INVOICE_TEXT=invoiceTextTemplate.substitute(
                                LIQUIDITY_THRESHOLD=helpers.formatPrice(self.liquidityThreshold, 'CHF'),
                                ACCESS_CODE=self.accessCode,
                                MEMBER_ID=bill.memberId,
                                INVOICE_IBAN=self.invoiceIban),
                            MEMBER_NAME=name,
                            BILL=str(bill),
                            TOTAL_GROSS_SALES_PRICE=helpers.formatPrice(bill.totalGrossSalesPrice(), 'CHF'),
                            TOTAL_PAYMENTS=helpers.formatPrice(bill.totalPayments, 'CHF'),
                            CORRECTION_TEXT=correctionText,
                            PREVIOUS_ACCOUNTING_DATE=bill.previousAccountingDate,
                            PREVIOUS_BALANCE=helpers.formatPrice(bill.previousBalance, 'CHF'),
                            CURRENT_ACCOUNTING_DATE=bill.currentAccountingDate,
                            CURRENT_BALANCE=helpers.formatPrice(bill.currentBalance(), 'CHF'),
                            LIQUIDITY_THRESHOLD=helpers.formatPrice(self.liquidityThreshold, 'CHF'),
                            INVOICE_IBAN=self.invoiceIban,
                            MEMBER_ID=bill.memberId,
                            ACCESS_CODE=self.accessCode,
                            REPLY_TO_ADDRESS=self.mailUser,
                            ACCOUNTANT_NAME=self.accountantName
                            )

                filename = bill.memberId+'.csv'
                self.sendEmail(email,
                        'Abrechnung vom {}'.format(bill.currentAccountingDate),
                        body, f'{self.billPath}{filename}', filename)

    def sendEmail(self, to, subject, body, path, attachmentName):
        message = MIMEMultipart()
        message["From"] = self.mailUser
        message["To"] = to
        message["Subject"] = subject
        message.attach(MIMEText(body, "plain"))

        with open(path, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())
        encoders.encode_base64(part)

        part.add_header(
            "Content-Disposition",
            "attachment; filename= \"" + attachmentName + "\"",
        )
        message.attach(part)
        text = message.as_string()

        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(self.mailHost, self.smtpPort, context=context) as server:
            result = server.login(self.mailUser, self.mailPassword)
            server.sendmail(self.mailUser, to, text)

        imap = imaplib.IMAP4_SSL(self.mailHost, self.imapPort)
        imap.login(self.mailUser, self.mailPassword)
        imap.append('INBOX.Sent', '\\Seen', imaplib.Time2Internaldate(time.time()), text.encode('utf8'))
        imap.logout()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Send an email containing their bill to each member.')
    parser.add_argument('accountingDir',
            help='Top-level tagtrail directory to process, usually data/accounting_YYYY-mm-dd/')
    parser.add_argument('accessCode',
            help="New access code to be sent to members",)
    parser.add_argument('accountantName',
            help="Name of the person responsible for this accounting.")
    parser.add_argument('--testRecipient',
            dest='testRecipient',
            help='If given, mails are sent to this email address instead of the real receivers.')
    args = parser.parse_args()

    MailSender(args.accountingDir,
            args.accessCode,
            args.accountantName,
            args.testRecipient).sendBills()

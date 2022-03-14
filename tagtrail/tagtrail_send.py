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
from string import Template
import time
import csv
import imaplib
import smtplib
import ssl
import os
import shutil
import logging
from email import encoders
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase

from . import helpers
from . import database

class MailSender(ABC):
    def __init__(self,
            accountingPath,
            accessCode,
            accountantName,
            configFilePath,
            testRecipient = None
            ):
        self.accessCode = accessCode
        self.logger = logging.getLogger('tagtrail.tagtrail_send.MailSender')
        self.billsToBeSentPath = f'{accountingPath}3_bills/to_be_sent/'
        self.billsAlreadySentPath = f'{accountingPath}3_bills/already_sent/'
        self.templatePath = accountingPath + '0_input/templates/'
        self.db = database.Database(f'{accountingPath}0_input/',
                configFilePath=configFilePath)
        self.billsToBeSent = []
        for member in self.db.members.values():
            if os.path.isfile(f'{self.billsToBeSentPath}{member.id}.csv'):
                self.billsToBeSent.append(self.db.readCsv(
                    f'{self.billsToBeSentPath}{member.id}.csv',
                    database.Bill))
            elif not os.path.isfile(f'{self.billsAlreadySentPath}{member.id}.csv'):
                answer = input('No bill found for {member.id} - Continue (yes/no)?')
                if answer != 'yes' and answer != 'y':
                    return

        self.emailTemplate = self.readTemplate(self.templatePath+'email.txt')
        self.invoiceAboveThresholdTemplate = self.readTemplate(
                self.templatePath+'invoice_above_threshold.txt')
        self.invoiceBelowThresholdTemplate = self.readTemplate(
                self.templatePath+'invoice_below_threshold.txt')
        self.correctionTextTemplate = self.readTemplate(
                self.templatePath+'correction.txt')

        self.accountantName = accountantName
        self.keyring = helpers.Keyring(self.db.config.get('general',
            'password_file_path'))
        self.mailPassword = self.keyring.get_and_ensure_password('tagtrail_send',
                        self.db.config.get('tagtrail_send', 'mail_user'))
        self.testRecipient = testRecipient

    def readTemplate(self, filename):
        with open(filename, 'r', encoding='utf-8') as template_file:
            template_file_content = template_file.read()
        return Template(template_file_content)

    def sendBills(self):
        billedMembersWithoutEmails = [bill.memberId for bill in self.billsToBeSent
                if self.db.members[bill.memberId].emails == []]
        if billedMembersWithoutEmails != []:
            answer = input('Bills cannot be sent to these members, ' + \
                  'as they have no email:\n' + \
                  f'{",".join(billedMembersWithoutEmails)}\n' + \
                    'Continue (yes/no)? ')
            if answer != 'yes' and answer != 'y':
                return

        for bill in self.billsToBeSent:
            if (self.db.config.getdecimal('general',
                'liquidity_threshold')
                    <= bill.currentBalance):
                invoiceTextTemplate = self.invoiceAboveThresholdTemplate
            else:
                invoiceTextTemplate = self.invoiceBelowThresholdTemplate

            if bill.correctionTransaction == 0:
                correctionText = ''
            else:
                correctionText = self.correctionTextTemplate.substitute(
                        CORRECTION_TRANSACTION=helpers.formatPrice(bill.correctionTransaction,
                            self.db.config.get('general', 'currency')),
                        CORRECTION_JUSTIFICATION=bill.correctionJustification)

            filename = bill.memberId+'.csv'
            for email in self.db.members[bill.memberId].emails:
                if not self.testRecipient is None:
                    self.logger.info(f'would send email to {email}, replaced by {self.testRecipient}: ')
                    email = self.testRecipient

                name = self.db.members[bill.memberId].name
                self.logger.info('Sending email to {}, {}'.format(email, name))
                body = self.emailTemplate.substitute(
                            INVOICE_TEXT=invoiceTextTemplate.substitute(
                                LIQUIDITY_THRESHOLD=helpers.formatPrice(
                                    self.db.config.getdecimal('general',
                                        'liquidity_threshold'),
                                    self.db.config.get('general', 'currency')),
                                ACCESS_CODE=self.accessCode,
                                MEMBER_ID=bill.memberId,
                                INVOICE_IBAN=self.db.config.get('general',
                                    'our_iban')),
                            MEMBER_NAME=name,
                            BILL=str(bill),
                            TOTAL_GROSS_SALES_PRICE=helpers.formatPrice(bill.totalGrossSalesPrice(), self.db.config.get('general', 'currency')),
                            TOTAL_PAYMENTS=helpers.formatPrice(bill.totalPayments, self.db.config.get('general', 'currency')),
                            CORRECTION_TEXT=correctionText,
                            PREVIOUS_ACCOUNTING_DATE=bill.previousAccountingDate,
                            PREVIOUS_BALANCE=helpers.formatPrice(bill.previousBalance, self.db.config.get('general', 'currency')),
                            CURRENT_ACCOUNTING_DATE=bill.currentAccountingDate,
                            CURRENT_BALANCE=helpers.formatPrice(bill.currentBalance, self.db.config.get('general', 'currency')),
                            LIQUIDITY_THRESHOLD=helpers.formatPrice(
                                self.db.config.getdecimal('general',
                                    'liquidity_threshold'),
                                self.db.config.get('general', 'currency')),
                            INVOICE_IBAN=self.db.config.get('general', 'our_iban'),
                            MEMBER_ID=bill.memberId,
                            ACCESS_CODE=self.accessCode,
                            REPLY_TO_ADDRESS=self.db.config.get('tagtrail_send', 'mail_user'),
                            ACCOUNTANT_NAME=self.accountantName
                            )

                try:
                    self.sendEmail(email,
                            self.db.config.get('tagtrail_send',
                                'email_subject')
                            .format(bill.previousAccountingDate,
                                bill.currentAccountingDate),
                            body, f'{self.billsToBeSentPath}{filename}', filename)
                except smtplib.SMTPRecipientsRefused as e:
                    if str(e).find('451') != -1:
                        self.logger.info("""Sending quota exceeded - Run tagtrail_send again later to send the remaining emails""")
                        return
                    else:
                        raise e
            # only move bill after it has been successfully sent to all
            # recipient emails
            if self.testRecipient is None:
                shutil.move(f'{self.billsToBeSentPath}{filename}',
                        f'{self.billsAlreadySentPath}{filename}')
            else:
                self.logger.info(f'would move {self.billsToBeSentPath}{filename} to {self.billsAlreadySentPath}{filename}')

    def sendEmail(self, to, subject, body, path, attachmentName):
        message = MIMEMultipart()
        message["From"] = self.db.config.get('tagtrail_send', 'mail_user')
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
        with smtplib.SMTP_SSL(
                self.db.config.get('tagtrail_send', 'mail_host'),
                self.db.config.get('tagtrail_send', 'smtp_port'),
                context=context) as server:
            result = server.login(
                    self.db.config.get('tagtrail_send', 'mail_user'),
                    self.mailPassword)
            server.sendmail(
                    self.db.config.get('tagtrail_send', 'mail_user'),
                    to,
                    text)

        imap = imaplib.IMAP4_SSL(
                self.db.config.get('tagtrail_send', 'mail_host'),
                self.db.config.get('tagtrail_send', 'imap_port'))
        imap.login(
                self.db.config.get('tagtrail_send', 'mail_user'),
                self.mailPassword)
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
    parser.add_argument('--configFilePath',
            dest='configFilePath',
            default='config/tagtrail.cfg',
            help='Path to the config file to be used.')
    parser.add_argument('--logLevel', dest='logLevel',
            help='Log level to write to console', default='INFO')
    args = parser.parse_args()
    helpers.configureLogger(logging.getLogger('tagtrail'), consoleLevel =
            logging.getLevelName(args.logLevel))

    MailSender(args.accountingDir,
            args.accessCode,
            args.accountantName,
            args.configFilePath,
            args.testRecipient).sendBills()

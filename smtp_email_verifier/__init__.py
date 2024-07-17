#!/usr/bin/env python

# python -u verify.py /tmp/emails.txt | tee /tmp/vemails.txt

# from verify_email import verify_email

import os
import sys
import argparse
import dns.resolver
import smtplib
import socket
import time

__version__ = '0.1.0'

verbose = False

def vprint(*args, **kwargs):
    if verbose:
        print(*args, **kwargs, flush=True)

class EmailVerifierError(Exception):
    def __init__(self, message, smtp_code=None):
        self.message = message
        self.smtp_code = smtp_code
        super().__init__(message)


class EmailVerifier:
    def __init__(self, helo: str, mailfrom: str, verbose=False):
        self.helo = helo
        self.mailfrom = mailfrom
        self.verbose = verbose

    def get_best_mx(self, mxlist: list[dns.resolver.Answer]):
        mx_sorted = sorted([(int(x.preference), str(x.exchange)) for x in mxlist])
        return mx_sorted[0][1]

    def verify_email(self, email):

        vprint(f"# Verifying {email}")

        try:
            addressToVerify = email
            domain = addressToVerify.split('@')[1]            
            records = dns.resolver.resolve(domain, 'MX')

            mxRecord = self.get_best_mx(records)

            # test resolve
            mx_ip = dns.resolver.resolve(mxRecord, 'A')[0].address

            server = smtplib.SMTP(timeout=10)
            server.set_debuglevel(self.verbose)
            server.connect(mxRecord)
            server.helo(self.helo)
            server.mail(self.mailfrom)
            code, message = server.rcpt(email)
            server.quit()
            vprint()
            if code == 250:
                return True            
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            raise EmailVerifierError(f"DNS error for {domain}")
        except Exception as e:
            raise EmailVerifierError(f"Other Error: {e}")

        raise EmailVerifierError(f"RCPT TO error: {code} {message}", smtp_code=code)

def get_args():

    global verbose

    def_from = 'noreply@example.com'
    def_helo = socket.getfqdn()

    parser = argparse.ArgumentParser()
    parser.add_argument('email', nargs='?', help='Email address to verify')
    parser.add_argument('--file', '-f', help='email list')
    parser.add_argument('--from', dest='_from', default=def_from, help='email for MAIL FROM')
    parser.add_argument('--helo', default=def_helo, help='HELO host')
    parser.add_argument('--retry', metavar='N', type=int, default=60, help='Retry (in seconds) if get temporary 4xx error (greylisting)')
    parser.add_argument('--max-retry', metavar='N', type=int, default=0, help='Do not retry for more then N seconds (use 180+, maybe 600)')
    parser.add_argument('--verbose', '-v', default=False, action='store_true', help='Verbosity for verifier logic')
    parser.add_argument('--smtp-verbose', '-s', default=False, action='store_true', help='Verbosity for SMTP conversation')

    args = parser.parse_args()

    if not args.email and not args.file:
        print("No email address or file provided", file=sys.stderr)
        parser.print_help()
        sys.exit(1)

    verbose = args.verbose

    return args


def verify_list(ev: EmailVerifier, maillist: list, can_retry=False): 

    retry_list = list()

    for email in maillist:
        try:
            r = ev.verify_email(email)
            print(email, flush=True)
        except EmailVerifierError as e:

            if can_retry and e.smtp_code is not None and e.smtp_code >= 400 and e.smtp_code < 500:
                retry_list.append(email)
                vprint(f"# {email}: {e} (will retry)")
            else:
                print(f"{email}: {e}", file=sys.stderr)

    return retry_list


def main():

    args = get_args()
    start = time.time()

    if args.max_retry > 0:
        last_retry = start + args.max_retry
    else:
        last_retry = 0

    maillist = list()

    ev = EmailVerifier(helo=args.helo, mailfrom=args._from, verbose=args.smtp_verbose)


    if args.email:
        try:
            r = ev.verify_email(args.email)
            print(args.email, flush=True)
        except EmailVerifierError as e:
            print(f"{args.email}: {e}", file=sys.stderr)
    else:
        with open(args.file, 'r') as f:
            for line in f:
                email = line.strip()
                if not email:
                    continue
                maillist.append(email)


        while maillist:            
            # check if next retry time will be too late
            next_retry = time.time() + args.retry
            can_retry = next_retry < last_retry
            retry_list = verify_list(ev, maillist, can_retry=can_retry)
            vprint(f"# RETRY: {len(retry_list)} emails")
            maillist = retry_list
            if maillist:
                vprint("# Sleep", args.retry, "seconds")
                time.sleep(args.retry)

    


if __name__ == '__main__':
    main()
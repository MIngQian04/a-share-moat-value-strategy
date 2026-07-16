# Security Policy

## Do not report secrets publicly

Never include Tushare tokens, API keys, account identifiers, broker details,
private datasets or personal portfolio records in a public Issue, Discussion,
Pull Request, screenshot or log.

If a secret is accidentally committed, revoke or rotate it immediately. Removing
the visible line is not sufficient because Git history may still contain it.

## Supported scope

This repository is a research tool. It does not place orders and should not be
given broker credentials. Security reports should focus on credential exposure,
unsafe file publication, dependency risks and incorrect handling of unavailable
data sources.

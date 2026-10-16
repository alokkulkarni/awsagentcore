# Merchant logos

Put a logo here to show it on the Money Hub's transaction rows, instead of the
merchant's initials. Use a logo you have the right to use.

- Name it after the merchant as the bank statement names it (the `merchant`
  field), in lower case, with a hyphen for each run of anything that isn't a
  letter or digit: `ALDI` is `aldi.svg`, `JUST EAT` is `just-eat.png`,
  `AMAZON.CO.UK` is `amazon-co-uk.svg`, `STARBUCKS` is `starbucks.svg`.
- SVG or PNG, roughly square (it's shown at 44 × 44 inside a rounded tile).
- Redeploy the page (`deploy_money_hub.sh`); the page picks them up itself.

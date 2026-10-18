"""
Built-in multilingual vocabulary used by the label-based (heuristic) parser.

Templates in ``sms_formats.txt`` can add more words without touching this file
(see the ``[keywords]`` section there). Everything is matched case-insensitively.
"""

# Field labels: "<label> : value" or "<label> value"
LABELS = {
    "balance": [
        # fa
        "موجودی", "موجودی حساب", "موجودی جدید", "مانده", "مانده حساب", "مانده جدید", "باقیمانده", "باقی مانده",
        # en / de / fr / es / tr / ar
        "balance", "bal", "new balance", "closing balance", "account balance", "ledger balance",
        "kontostand", "saldo", "neuer saldo", "solde", "nouveau solde", "saldo actual", "saldo disponible",
        "bakiye", "kalan bakiye", "الرصيد", "رصيد",
    ],
    "available": [
        "موجودی قابل برداشت", "مانده قابل برداشت", "قابل برداشت", "قابل استفاده",
        "available balance", "avail bal", "avl bal", "available", "verfügbar", "verfügbarer betrag",
        "solde disponible", "disponible", "kullanılabilir bakiye", "الرصيد المتاح",
    ],
    "fee": ["کارمزد", "مبلغ کارمزد", "fee", "fees", "charges", "gebühr", "entgelt", "frais", "comisión", "komisyon",
            "رسوم"],
    "amount": [
        "مبلغ", "مبلغ تراکنش", "مبلغ کل", "مبلغ برداشت", "مبلغ واریز", "مبلغ خرید", "مقدار",
        "amount", "amt", "txn amount", "transaction amount", "betrag", "montant", "importe", "monto",
        "tutar", "işlem tutarı", "المبلغ",
    ],
    "tracking": ["شماره پیگیری", "کد پیگیری", "پیگیری", "کد رهگیری", "شماره رهگیری", "رهگیری",
                 "tracking", "tracking no", "trace", "trace no"],
    "ref": [
        "شماره مرجع", "کد مرجع", "مرجع", "شماره سند", "سند", "شماره تراکنش", "شناسه تراکنش", "شناسه پرداخت",
        "شناسه", "ارجاع", "شماره ارجاع",
        "ref", "ref no", "reference", "reference no", "txn id", "transaction id", "utr", "rrn",
        "referenz", "référence", "referencia", "referans", "المرجع", "رقم العملية",
    ],
    "date": [
        "تاریخ", "زمان", "ساعت", "تاریخ و ساعت", "تاریخ تراکنش", "تاریخ و زمان",
        "date", "time", "date/time", "date & time", "datum", "zeit", "uhrzeit", "buchungsdatum",
        "heure", "fecha", "hora", "tarih", "saat", "التاريخ", "الوقت",
    ],
    "merchant": [
        "فروشگاه", "نام فروشگاه", "پذیرنده", "نام پذیرنده", "محل خرید", "محل",
        "merchant", "store", "shop", "händler", "geschäft", "commerçant", "comercio", "establecimiento",
        "işyeri", "التاجر",
    ],
    "person": [
        "گیرنده", "نام گیرنده", "فرستنده", "نام فرستنده", "واریز کننده", "نام واریز کننده", "پرداخت کننده",
        "صاحب حساب مقصد", "صاحب حساب", "طرف حساب", "به نام", "در وجه",
        "payee", "beneficiary", "sender", "recipient", "remitter", "empfänger", "absender", "auftraggeber",
        "bénéficiaire", "émetteur", "beneficiario", "ordenante", "alıcı", "gönderen", "المستفيد",
    ],
    "desc": [
        "بابت", "شرح", "توضیحات", "توضیح", "شرح تراکنش", "علت", "موضوع",
        "description", "desc", "narration", "remarks", "details", "verwendungszweck", "buchungstext",
        "libellé", "motif", "concepto", "açıklama", "الوصف",
    ],
    "account": [
        "حساب", "از حساب", "به حساب", "شماره حساب", "کارت", "شماره کارت", "از کارت", "به کارت", "سپرده",
        "شماره سپرده", "حساب مبدا", "حساب مقصد",
        "account", "a/c", "acct", "card", "card no", "konto", "karte", "iban", "compte", "carte", "cuenta",
        "tarjeta", "hesap", "kart", "الحساب", "البطاقة",
    ],
    "type": ["نوع", "نوع تراکنش", "عملیات", "نوع عملیات", "transaction type", "type", "typ", "buchungsart",
             "opération", "tipo", "işlem"],
    "party": ["مبدا", "مقصد", "مبدأ"],
}

# Labels that only count when followed by ":" (too common as normal words otherwise)
COLON_LABELS = {
    "party": ["از", "به", "from", "to", "von", "an", "de", "à", "para"],
    "merchant": ["at", "bei", "chez", "en"],
}

# Words that decide the direction of a transaction
TYPE_IN = [
    "واریز", "واریزی", "دریافت", "سود", "بستانکار", "عودت", "برگشت", "استرداد",
    "credit", "credited", "deposit", "deposited", "received", "incoming", "refund", "refunded", "salary",
    "interest", "cashback", "reversal", "cr",
    "gutschrift", "eingang", "zahlungseingang", "einzahlung", "gehalt", "erstattung", "rückbuchung", "zinsen",
    "virement reçu", "crédit", "versement", "remboursement", "salaire",
    "abono", "ingreso", "depósito", "recibido", "reembolso", "nómina",
    "gelen", "yatırıldı", "alacak", "iade", "إيداع", "ايداع", "استلام", "راتب",
]
TYPE_OUT = [
    "کارت به کارت", "برداشت", "خرید", "پرداخت", "انتقال", "کسر", "بدهکار", "قسط", "شارژ", "قبض", "پایا",
    "ساتنا", "حواله", "چک",
    "debit", "debited", "withdrawal", "withdrawn", "purchase", "payment", "paid", "spent", "transfer", "sent",
    "charge", "charged", "pos", "atm", "bill", "dr",
    "lastschrift", "abbuchung", "belastung", "auszahlung", "kartenzahlung", "zahlung", "überweisung",
    "abhebung", "einkauf", "barabhebung",
    "débit", "paiement", "achat", "retrait", "prélèvement", "virement",
    "cargo", "compra", "pago", "retiro", "transferencia", "débito",
    "harcama", "ödeme", "çekim", "borç", "سحب", "شراء", "دفع", "تحويل", "خصم",
]

# One-time-password / verification messages are never transactions, even if they mention an amount.
OTP_WORDS = [
    "رمز", "پویا", "کد تایید", "کد تأیید", "کد فعال سازی", "کد ورود", "کد یکبار",
    "otp", "password", "passcode", "verification", "verify", "one-time", "one time code", "security code",
    "tan", "mtan", "pushtan", "bestätigungscode", "code de vérification", "código de verificación",
    "doğrulama", "şifre", "رمز التحقق",
]

# A short line containing one of these words (and no digits) is treated as the bank name
BANK_WORDS = ["بانک", "bank", "sparkasse", "banque", "banco", "banka", "credit union"]

# Words around a merchant/person name that are not part of the name
STOPWORDS_EDGE = ["از", "به", "در", "بابت", "با", "فروشگاه", "پذیرنده", "محل", "توسط", "موفق", "انجام شد",
                  "at", "to", "from", "in", "on", "with", "bei", "von", "an", "chez", "en"]

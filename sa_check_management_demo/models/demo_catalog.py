"""Names and banks used to build Egyptian-looking demo data."""

COMPANY_PREFIXES = ["شركة", "مؤسسة", "مجموعة", "مصنع", "مكتب"]
COMPANY_NAMES = [
    "النور", "الدلتا", "الأهرام", "النيل", "المستقبل", "الفجر", "السلام", "الوادي", "الصفا", "المروة",
    "الرواد", "الأمل", "الريادة", "الشروق", "الحرية", "الإسراء", "الهدى", "الزهراء", "الفرسان", "النخبة",
    "الأصالة", "التقدم", "الفيروز", "اللؤلؤة", "الماسة", "الياسمين", "الربيع", "الجوهرة", "المنار", "البركة",
]
CUSTOMER_ACTIVITIES = [
    "للتجارة", "للأغذية", "للأجهزة الكهربائية", "للتوزيع", "للأدوية", "للملابس", "للأدوات الصحية",
    "للمواد الغذائية", "للسيراميك", "للمنظفات",
]
VENDOR_ACTIVITIES = [
    "للاستيراد والتصدير", "للصناعات الهندسية", "للحديد والصلب", "للتوريدات", "للنقل والشحن",
    "للمقاولات", "للتغليف", "للكيماويات", "للبلاستيك", "للطباعة",
]
CITIES = ["القاهرة", "الجيزة", "الإسكندرية", "المنصورة", "طنطا", "الزقازيق", "أسيوط", "بورسعيد", "السويس", "دمياط"]
LAWYERS = ["الأستاذ حسن عبد الرحمن", "الأستاذة منى الشريف", "الأستاذ كريم فتحي", "مكتب السيد للمحاماة",
           "الأستاذ وليد منصور"]
COURTS = ["محكمة القاهرة الاقتصادية", "محكمة الجيزة الاقتصادية", "محكمة الإسكندرية الاقتصادية",
          "محكمة جنح مدينة نصر"]
BANKS = [
    ("البنك الأهلي المصري", "NBEGEGCX"),
    ("بنك مصر", "BMISEGCX"),
    ("البنك التجاري الدولي", "CIBEEGCX"),
    ("بنك القاهرة", "BCAIEGCX"),
    ("بنك QNB الأهلي", "QNBAEGCX"),
    ("البنك العربي الأفريقي الدولي", "ARAIEGCX"),
    ("بنك HSBC مصر", "EBBKEGCX"),
    ("بنك الإسكندرية", "ALEXEGCX"),
    ("بنك فيصل الإسلامي", "FIEGEGCX"),
    ("بنك أبوظبي الأول مصر", "NBADEGCX"),
]
COMPANY_BANK_JOURNALS = [("CIB Demo", "CIBD"), ("NBE Demo", "NBED"), ("Banque Misr Demo", "BMDM")]
LOCATIONS = [
    ("الخزنة الرئيسية", "safe"),
    ("فرع مدينة نصر", "branch"),
    ("فرع الإسكندرية", "branch"),
    ("المندوب أحمد سمير", "person"),
    ("المندوب محمود علي", "person"),
    ("المندوب مصطفى حسن", "person"),
]

DEFAULT_PASSWORD = "Demo@1234"
# (login, name, role, groups besides Internal User)
DEMO_USERS = [
    ("demo.clerk", "سارة إبراهيم - موظفة شيكات", "clerk", ["sa_check_management.group_check_user"]),
    ("demo.treasury1", "محمد عادل - خزينة", "treasury", ["sa_check_management.group_check_treasury"]),
    ("demo.treasury2", "هبة مصطفى - خزينة", "treasury", ["sa_check_management.group_check_treasury"]),
    ("demo.approver", "عمرو جلال - معتمد مالي", "approver", ["sa_check_management.group_check_approver"]),
    ("demo.manager", "ياسر الشريف - مدير الشيكات", "manager", ["sa_check_management.group_check_manager"]),
    ("demo.accountant", "رانيا فؤاد - محاسبة", "accountant",
     ["sa_check_management.group_check_accountant", "account.group_account_invoice"]),
    ("demo.auditor", "خالد منير - مراجع", "auditor", ["sa_check_management.group_check_auditor"]),
    ("demo.rep1", "أحمد سمير - مندوب", "rep", ["sa_check_management.group_check_user"]),
    ("demo.rep2", "محمود علي - مندوب", "rep", ["sa_check_management.group_check_user"]),
    ("demo.rep3", "مصطفى حسن - مندوب", "rep", ["sa_check_management.group_check_user"]),
]

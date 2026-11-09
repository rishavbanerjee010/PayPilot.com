"""
catalog.py — PayPilot trusted product catalogue (all prices in INR).

This module is the single source of truth for products and prices.
The backend NEVER trusts prices sent by the frontend; cart totals are
always recomputed from this catalogue.

It also implements the pure search / compare / details logic used by the
AI agent's function tools (see agent.py).
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

CURRENCY = "INR"
CURRENCY_SYMBOL = "\u20b9"  # ₹

CATEGORIES: List[str] = [
    "Electronics",
    "Smartphones",
    "Laptops",
    "Accessories",
    "Fashion",
    "Home & Lifestyle",
    "Appliances",
    "Beauty & Personal Care",
    "Sports & Fitness",
]

# ---------------------------------------------------------------------------
# Catalogue — 100 curated demo products with realistic Indian market prices
# (whole rupees, stored as int; formatted with the Indian numbering system)
# ---------------------------------------------------------------------------

PRODUCTS: List[Dict[str, Any]] = [
    # ----------------------------- Smartphones -----------------------------
    {
        "id": "PP-001",
        "name": "Redmi Note 13 Pro 5G",
        "category": "Smartphones",
        "price_inr": 21499,
        "short_description": "200MP camera flagship killer with 120Hz AMOLED at a budget price.",
        "description": "The Redmi Note 13 Pro 5G brings a 200MP main camera, a 120Hz 1.5K AMOLED display and 67W fast charging to the mid-range segment. It is one of the best value camera phones you can buy under \u20b925,000 in India.",
        "specs": {
            "Display": "6.67\" 1.5K AMOLED, 120Hz",
            "Processor": "Snapdragon 7s Gen 2",
            "RAM / Storage": "8GB / 128GB",
            "Camera": "200MP + 8MP + 2MP, 16MP front",
            "Battery": "5100mAh, 67W fast charging",
            "Warranty": "1 year",
        },
        "rating": 4.3,
        "num_reviews": 18240,
        "stock": 42,
        "best_for": ["students", "photography", "budget buyers"],
        "featured": False,
    },
    {
        "id": "PP-002",
        "name": "Samsung Galaxy A35 5G",
        "category": "Smartphones",
        "price_inr": 27999,
        "short_description": "IP67-rated Galaxy with Super AMOLED display and 4 years of updates.",
        "description": "The Galaxy A35 5G offers a vibrant Super AMOLED 120Hz display, IP67 dust and water resistance, and Samsung's promise of 4 generations of OS upgrades. A dependable all-rounder for everyday use.",
        "specs": {
            "Display": "6.6\" Super AMOLED, 120Hz",
            "Processor": "Exynos 1380",
            "RAM / Storage": "8GB / 128GB",
            "Camera": "50MP OIS + 8MP + 5MP, 13MP front",
            "Battery": "5000mAh, 25W charging",
            "Warranty": "1 year",
        },
        "rating": 4.2,
        "num_reviews": 9310,
        "stock": 30,
        "best_for": ["everyday use", "students"],
        "featured": False,
    },
    {
        "id": "PP-003",
        "name": "OnePlus 12R",
        "category": "Smartphones",
        "price_inr": 39999,
        "short_description": "Flagship-grade Snapdragon 8 Gen 2 performance with 100W charging.",
        "description": "The OnePlus 12R pairs last year's flagship Snapdragon 8 Gen 2 with a ProXDR 120Hz display and a huge 5500mAh battery with 100W SUPERVOOC charging. Ideal for gamers and power users who want flagship speed without flagship pricing.",
        "specs": {
            "Display": "6.78\" LTPO4 AMOLED, 120Hz",
            "Processor": "Snapdragon 8 Gen 2",
            "RAM / Storage": "12GB / 256GB",
            "Camera": "50MP OIS + 8MP + 2MP, 16MP front",
            "Battery": "5500mAh, 100W SUPERVOOC",
            "Warranty": "1 year",
        },
        "rating": 4.5,
        "num_reviews": 12480,
        "stock": 25,
        "best_for": ["gaming", "power users", "students"],
        "featured": True,
    },
    {
        "id": "PP-004",
        "name": "Google Pixel 8a",
        "category": "Smartphones",
        "price_inr": 44999,
        "short_description": "Best-in-class camera with 7 years of Android updates and AI features.",
        "description": "The Pixel 8a delivers Google's signature computational photography, the Tensor G3 chip with on-device AI features, and 7 years of OS and security updates — the longest support window in this price segment.",
        "specs": {
            "Display": "6.1\" OLED, 120Hz",
            "Processor": "Google Tensor G3",
            "RAM / Storage": "8GB / 128GB",
            "Camera": "64MP OIS + 13MP ultrawide, 13MP front",
            "Battery": "4492mAh, 18W charging",
            "Warranty": "1 year",
        },
        "rating": 4.4,
        "num_reviews": 6520,
        "stock": 18,
        "best_for": ["photography", "software updates", "AI features"],
        "featured": False,
    },
    # ------------------------------ Laptops --------------------------------
    {
        "id": "PP-005",
        "name": "Lenovo IdeaPad Slim 3",
        "category": "Laptops",
        "price_inr": 41990,
        "short_description": "Light everyday laptop with Ryzen 5 and 16GB RAM for students.",
        "description": "The IdeaPad Slim 3 is a dependable budget laptop for classes, browsing and office work. The Ryzen 5 7530U with 16GB RAM handles multi-tab studying and light programming comfortably.",
        "specs": {
            "Processor": "AMD Ryzen 5 7530U",
            "RAM": "16GB DDR4",
            "Storage": "512GB SSD",
            "Display": "15.6\" FHD, 250 nits",
            "Weight": "1.62 kg",
            "Battery": "Up to 7 hours",
            "Warranty": "1 year",
        },
        "rating": 4.1,
        "num_reviews": 3860,
        "stock": 35,
        "best_for": ["students", "everyday use", "budget buyers"],
        "featured": False,
    },
    {
        "id": "PP-006",
        "name": "HP Pavilion 15",
        "category": "Laptops",
        "price_inr": 58990,
        "short_description": "13th-gen i5 with 16GB RAM — a solid programming and office machine.",
        "description": "The HP Pavilion 15 combines a 13th-gen Intel Core i5 with 16GB RAM and a fast 512GB SSD. It compiles code, runs IDEs and virtual machines smoothly, making it a great pick under \u20b960,000 for developers and working professionals.",
        "specs": {
            "Processor": "Intel Core i5-1335U",
            "RAM": "16GB DDR4",
            "Storage": "512GB NVMe SSD",
            "Display": "15.6\" FHD IPS, 250 nits",
            "Graphics": "Intel Iris Xe",
            "Weight": "1.75 kg",
            "Battery": "Up to 8 hours",
            "Warranty": "1 year",
        },
        "rating": 4.2,
        "num_reviews": 5120,
        "stock": 28,
        "best_for": ["programming", "office work", "students"],
        "featured": True,
    },
    {
        "id": "PP-007",
        "name": "ASUS TUF Gaming F15",
        "category": "Laptops",
        "price_inr": 69990,
        "short_description": "Gaming laptop with RTX 3050, 144Hz display and military-grade build.",
        "description": "The TUF Gaming F15 pairs a 12th-gen Core i5 with an NVIDIA RTX 3050 and a 144Hz IPS display. Beyond gaming it is also a capable machine for video editing, 3D work and heavy multitasking.",
        "specs": {
            "Processor": "Intel Core i5-12500H",
            "RAM": "16GB DDR4",
            "Storage": "512GB NVMe SSD",
            "Display": "15.6\" FHD IPS, 144Hz",
            "Graphics": "NVIDIA RTX 3050 4GB",
            "Weight": "2.2 kg",
            "Battery": "Up to 6 hours",
            "Warranty": "1 year",
        },
        "rating": 4.3,
        "num_reviews": 4470,
        "stock": 15,
        "best_for": ["gaming", "video editing", "programming"],
        "featured": False,
    },
    {
        "id": "PP-008",
        "name": "Apple MacBook Air M2",
        "category": "Laptops",
        "price_inr": 89990,
        "short_description": "Fanless M2 performance with 18-hour battery in a 1.24 kg body.",
        "description": "The MacBook Air M2 remains the benchmark for thin-and-light laptops. The M2 chip delivers desktop-class performance with silent, fanless cooling and up to 18 hours of battery — a favourite among developers and professionals.",
        "specs": {
            "Processor": "Apple M2 (8-core CPU, 8-core GPU)",
            "RAM": "8GB unified memory",
            "Storage": "256GB SSD",
            "Display": "13.6\" Liquid Retina, 500 nits",
            "Weight": "1.24 kg",
            "Battery": "Up to 18 hours",
            "Warranty": "1 year",
        },
        "rating": 4.7,
        "num_reviews": 8930,
        "stock": 12,
        "best_for": ["professionals", "programming", "students"],
        "featured": True,
    },
    {
        "id": "PP-009",
        "name": "Acer Aspire Lite",
        "category": "Laptops",
        "price_inr": 34990,
        "short_description": "The most affordable 16GB laptop in the store — great value for students.",
        "description": "The Aspire Lite packs a 12th-gen Core i5 and 16GB RAM into a slim metal body at a very aggressive price. For students who need many browser tabs, documents and light coding, it is hard to beat at \u20b935,000.",
        "specs": {
            "Processor": "Intel Core i5-1235U",
            "RAM": "16GB DDR4",
            "Storage": "512GB SSD",
            "Display": "14\" FHD IPS",
            "Weight": "1.4 kg",
            "Battery": "Up to 7 hours",
            "Warranty": "1 year",
        },
        "rating": 4.0,
        "num_reviews": 2140,
        "stock": 40,
        "best_for": ["students", "budget buyers", "everyday use"],
        "featured": False,
    },
    # ----------------------------- Electronics ------------------------------
    {
        "id": "PP-010",
        "name": "Sony WH-1000XM5",
        "category": "Electronics",
        "price_inr": 26990,
        "short_description": "Industry-leading noise cancellation with 30-hour battery life.",
        "description": "The WH-1000XM5 is the benchmark for wireless ANC headphones. Eight microphones, crystal-clear calls, 30 hours of battery and multipoint pairing make it ideal for flights, offices and focused work sessions.",
        "specs": {
            "Type": "Over-ear wireless ANC",
            "Battery": "30 hours (ANC on)",
            "Charging": "USB-C, 3 min = 3 hrs playback",
            "Codecs": "LDAC, AAC, SBC",
            "Weight": "250 g",
            "Warranty": "1 year",
        },
        "rating": 4.6,
        "num_reviews": 15310,
        "stock": 22,
        "best_for": ["travel", "music", "work calls"],
        "featured": True,
    },
    {
        "id": "PP-011",
        "name": "boAt Airdopes 141",
        "category": "Electronics",
        "price_inr": 1299,
        "short_description": "True wireless earbuds with 42 hours of total playback, under \u20b91,500.",
        "description": "The Airdopes 141 deliver a 42-hour total playback with the case, low-latency BEAST mode for gaming, and IPX4 splash resistance — all at a price that is easy on the pocket.",
        "specs": {
            "Type": "True wireless earbuds",
            "Battery": "42 hours (with case)",
            "Water resistance": "IPX4",
            "Latency mode": "BEAST mode (low latency)",
            "Charging": "USB-C",
            "Warranty": "1 year",
        },
        "rating": 4.0,
        "num_reviews": 48210,
        "stock": 120,
        "best_for": ["budget buyers", "workouts", "students"],
        "featured": False,
    },
    {
        "id": "PP-012",
        "name": "JBL Flip 6",
        "category": "Electronics",
        "price_inr": 8999,
        "short_description": "IP67 waterproof portable speaker with bold JBL Pro sound.",
        "description": "The Flip 6 is a rugged, waterproof Bluetooth speaker with a racetrack driver and dual passive radiators for surprisingly big bass. 12 hours of playtime and PartyBoost pairing make it a party staple.",
        "specs": {
            "Type": "Portable Bluetooth speaker",
            "Battery": "12 hours",
            "Waterproof": "IP67 dust & waterproof",
            "Extras": "PartyBoost pairing",
            "Weight": "550 g",
            "Warranty": "1 year",
        },
        "rating": 4.4,
        "num_reviews": 9840,
        "stock": 33,
        "best_for": ["parties", "outdoors", "travel"],
        "featured": False,
    },
    {
        "id": "PP-013",
        "name": "Apple Watch SE (2nd Gen)",
        "category": "Electronics",
        "price_inr": 24999,
        "short_description": "Essential Apple Watch features with crash detection at a lower price.",
        "description": "The Watch SE 2nd Gen covers the core Apple Watch experience: fitness tracking, heart-rate notifications, crash detection and deep iPhone integration, without the premium of the Series line.",
        "specs": {
            "Case": "40mm aluminium",
            "Display": "Retina LTPO OLED",
            "Battery": "Up to 18 hours",
            "Water resistance": "50m (WR50)",
            "Sensors": "Heart rate, crash detection",
            "Warranty": "1 year",
        },
        "rating": 4.5,
        "num_reviews": 6120,
        "stock": 20,
        "best_for": ["fitness", "iPhone users"],
        "featured": False,
    },
    {
        "id": "PP-022",
        "name": "Amazon Echo Dot (5th Gen)",
        "category": "Electronics",
        "price_inr": 4499,
        "short_description": "Smart speaker with Alexa — the easiest way to start a smart home.",
        "description": "The 5th-gen Echo Dot has bigger, richer sound than its predecessor and doubles as a smart home hub. Use Alexa to control lights, set reminders, play music and answer questions hands-free.",
        "specs": {
            "Type": "Smart speaker with Alexa",
            "Audio": "1.73\" front-firing speaker",
            "Extras": "Tap actions, temperature sensor",
            "Connectivity": "Wi-Fi, Bluetooth, Thread",
            "Warranty": "1 year",
        },
        "rating": 4.4,
        "num_reviews": 21650,
        "stock": 55,
        "best_for": ["smart home", "music", "everyday use"],
        "featured": False,
    },
    # ----------------------------- Accessories ------------------------------
    {
        "id": "PP-014",
        "name": "Logitech MX Master 3S",
        "category": "Accessories",
        "price_inr": 8495,
        "short_description": "Premium productivity mouse with quiet clicks and 8K DPI sensor.",
        "description": "The MX Master 3S is the default choice for professionals: an ultra-quiet click mechanism, an 8000 DPI any-surface sensor, MagSpeed electromagnetic scrolling and the thumbwheel make long work sessions effortless.",
        "specs": {
            "Sensor": "8000 DPI Darkfield",
            "Clicks": "90% quieter than MX Master 3",
            "Scroll": "MagSpeed electromagnetic",
            "Battery": "70 days, USB-C quick charge",
            "Connectivity": "Bluetooth + Logi Bolt USB receiver",
            "Warranty": "1 year",
        },
        "rating": 4.6,
        "num_reviews": 7290,
        "stock": 26,
        "best_for": ["programmers", "designers", "office work"],
        "featured": False,
    },
    {
        "id": "PP-015",
        "name": "Anker 325 Power Bank 20000mAh",
        "category": "Accessories",
        "price_inr": 3999,
        "short_description": "20,000mAh power bank with 20W fast charging for phones and earbuds.",
        "description": "A 20,000mAh Anker power bank charges a typical smartphone 4-5 times, with 20W USB-C PD fast charging, trickle mode for small gadgets and Anker's MultiProtect safety system.",
        "specs": {
            "Capacity": "20000mAh",
            "Output": "20W USB-C PD + 18W USB-A",
            "Ports": "1x USB-C, 1x USB-A",
            "Recharge time": "~5.5 hours",
            "Warranty": "18 months",
        },
        "rating": 4.3,
        "num_reviews": 11400,
        "stock": 48,
        "best_for": ["travel", "students", "everyday use"],
        "featured": False,
    },
    {
        "id": "PP-016",
        "name": "Keychron K2 Wireless Keyboard",
        "category": "Accessories",
        "price_inr": 7499,
        "short_description": "Hot-swappable 75% mechanical keyboard with Bluetooth and Mac support.",
        "description": "The Keychron K2 packs a 75% layout with Gateron brown switches, hot-swappable sockets and dual Bluetooth/USB-C connectivity in a sturdy aluminium frame. A favourite with writers and programmers.",
        "specs": {
            "Layout": "75% (84 keys)",
            "Switches": "Gateron brown, hot-swappable",
            "Connectivity": "Bluetooth 5.1 + USB-C",
            "Battery": "4000mAh, ~3 weeks typical use",
            "Compatibility": "Windows / macOS / Linux",
            "Warranty": "1 year",
        },
        "rating": 4.5,
        "num_reviews": 3320,
        "stock": 19,
        "best_for": ["programmers", "writers", "gaming"],
        "featured": False,
    },
    # ------------------------------- Fashion --------------------------------
    {
        "id": "PP-017",
        "name": "Levi's 511 Slim Fit Jeans",
        "category": "Fashion",
        "price_inr": 2999,
        "short_description": "Classic slim-fit denim that works for office and weekends.",
        "description": "Levi's 511 sits below the waist with a slim leg — modern but not skinny. Durable cotton denim that keeps its shape after washes, in an indigo shade that goes with everything.",
        "specs": {
            "Fit": "Slim fit",
            "Material": "98% cotton, 2% elastane",
            "Closure": "Zip fly, button",
            "Care": "Machine wash cold",
            "Warranty": "Not applicable",
        },
        "rating": 4.2,
        "num_reviews": 5610,
        "stock": 60,
        "best_for": ["everyday wear", "office", "students"],
        "featured": False,
    },
    {
        "id": "PP-018",
        "name": "Titan Neo Analog Watch",
        "category": "Fashion",
        "price_inr": 5995,
        "short_description": "Slim stainless-steel dress watch with sapphire-coated glass.",
        "description": "The Titan Neo is a clean, minimalist analog watch with a slim stainless-steel case, mineral glass and 50m water resistance — an easy pick for formal wear and gifting.",
        "specs": {
            "Movement": "Quartz analog",
            "Case": "Stainless steel, 40mm",
            "Glass": "Mineral (sapphire coated)",
            "Water resistance": "50m",
            "Warranty": "2 years",
        },
        "rating": 4.3,
        "num_reviews": 2870,
        "stock": 34,
        "best_for": ["gifting", "office", "formal wear"],
        "featured": False,
    },
    {
        "id": "PP-019",
        "name": "Nike Revolution 7 Running Shoes",
        "category": "Fashion",
        "price_inr": 3695,
        "short_description": "Lightweight daily running shoes with soft foam cushioning.",
        "description": "The Revolution 7 is Nike's entry-level runner: breathable knit upper, soft foam midsole and a grip pattern that handles treadmill and road. A comfortable starter shoe for jogging and gym.",
        "specs": {
            "Use": "Road running / walking",
            "Upper": "Engineered knit",
            "Midsole": "Soft foam",
            "Closure": "Lace-up",
            "Warranty": "Not applicable",
        },
        "rating": 4.1,
        "num_reviews": 4180,
        "stock": 45,
        "best_for": ["running", "gym", "beginners"],
        "featured": False,
    },
    # -------------------------- Home & Lifestyle ----------------------------
    {
        "id": "PP-020",
        "name": "Milton Thermosteel Flask 1L",
        "category": "Home & Lifestyle",
        "price_inr": 1099,
        "short_description": "Keeps drinks hot or cold for 24 hours — ideal for travel and office.",
        "description": "Milton's Thermosteel flask uses double-wall vacuum insulation to hold temperature for a full 24 hours. The 1L body is leak-proof, rust-free stainless steel and easy to clean.",
        "specs": {
            "Capacity": "1000 ml",
            "Insulation": "Double-wall vacuum, 24h",
            "Body": "Stainless steel",
            "Leak proof": "Yes",
            "Warranty": "1 year",
        },
        "rating": 4.2,
        "num_reviews": 15630,
        "stock": 80,
        "best_for": ["travel", "office", "students"],
        "featured": False,
    },
    {
        "id": "PP-021",
        "name": "Prestige PIC 16.0 Induction Cooktop",
        "category": "Home & Lifestyle",
        "price_inr": 2790,
        "short_description": "1900W induction cooktop with Indian-menu presets and auto shut-off.",
        "description": "The Prestige PIC 16.0 heats faster than a gas stove with 1900W of power, Indian-menu one-touch presets, and safety features like auto shut-off and voltage protection.",
        "specs": {
            "Power": "1900W",
            "Presets": "Indian menu, keep warm",
            "Safety": "Auto shut-off, voltage protection",
            "Warranty": "1 year",
        },
        "rating": 4.2,
        "num_reviews": 7460,
        "stock": 38,
        "best_for": ["kitchen", "everyday use"],
        "featured": False,
    },
    # ----------------------------- Smartphones -----------------------------
    {
        "id": "PP-023",
        "name": "Nothing Phone (2a) 5G",
        "category": "Smartphones",
        "price_inr": 23999,
        "short_description": "Transparent-design 5G phone with clean Nothing OS and Glyph lights at a mid-range price.",
        "description": "The Nothing Phone (2a) stands out with its iconic transparent design, Glyph LED notifications and the smooth Nothing OS 2.5 built on Android 14. Powered by the Dimensity 7200 Pro, it handles gaming and multitasking well while promising years of Android updates.",
        "specs": {
            "Display": "6.7\" Flexible AMOLED, 120Hz",
            "Processor": "MediaTek Dimensity 7200 Pro",
            "RAM / Storage": "8GB / 128GB",
            "Camera": "50MP OIS + 50MP, 32MP front",
            "Battery": "5000mAh, 45W fast charging",
            "Warranty": "1 year",
        },
        "rating": 4.2,
        "num_reviews": 5420,
        "stock": 25,
        "best_for": ["students", "design lovers", "clean software fans"],
        "featured": False,
    },
    {
        "id": "PP-024",
        "name": "vivo T3 5G",
        "category": "Smartphones",
        "price_inr": 19999,
        "short_description": "Dimensity 7200 performance with a Sony OIS camera and 44W fast charging under ₹20,000.",
        "description": "The vivo T3 5G pairs the MediaTek Dimensity 7200 with a 50MP Sony IMX882 camera with OIS, delivering flagship-style photography on a tight budget. Its 5000mAh battery supports 44W fast charging, topping up in about 50 minutes.",
        "specs": {
            "Display": "6.67\" FHD+ AMOLED, 120Hz",
            "Processor": "MediaTek Dimensity 7200",
            "RAM / Storage": "8GB / 128GB",
            "Camera": "50MP Sony IMX882 OIS + 2MP, 16MP front",
            "Battery": "5000mAh, 44W fast charging",
            "Warranty": "1 year",
        },
        "rating": 4.1,
        "num_reviews": 8240,
        "stock": 38,
        "best_for": ["budget buyers", "students", "gaming"],
        "featured": False,
    },
    # ------------------------------- Laptops --------------------------------
    {
        "id": "PP-025",
        "name": "HP Victus 15 Gaming Laptop",
        "category": "Laptops",
        "price_inr": 59990,
        "short_description": "144Hz gaming laptop with RTX 2050 graphics and Ryzen 5 power for esports and engineering work.",
        "description": "The HP Victus 15 combines a Ryzen 5 7535HS processor with NVIDIA RTX 2050 graphics and a 144Hz FHD display, making it a solid entry point for esports titles like Valorant and GTA V. 16GB of dual-channel DDR5 memory keeps design tools and IDEs responsive too.",
        "specs": {
            "Display": "15.6\" FHD, 144Hz, anti-glare",
            "Processor": "AMD Ryzen 5 7535HS",
            "Graphics": "NVIDIA RTX 2050 4GB",
            "RAM / Storage": "16GB DDR5 / 512GB SSD",
            "Battery": "70Wh, 200W adapter",
            "Warranty": "1 year onsite",
        },
        "rating": 4.2,
        "num_reviews": 3120,
        "stock": 12,
        "best_for": ["gamers", "engineering students", "creators"],
        "featured": False,
    },
    # ----------------------------- Electronics ------------------------------
    {
        "id": "PP-026",
        "name": "Xiaomi Smart TV X Pro 43\"",
        "category": "Electronics",
        "price_inr": 27999,
        "short_description": "43-inch 4K Google TV with Dolby Vision and 30W speakers for an affordable big-screen setup.",
        "description": "The Xiaomi Smart TV X Pro (43) runs Google TV with PatchWall, supports Dolby Vision, HDR10+ and Dolby Audio through its 30W speaker system. With 3 HDMI ports and built-in Chromecast, it is an easy centrepiece for movies and cricket nights.",
        "specs": {
            "Display": "43\" 4K UHD LED, Dolby Vision",
            "OS": "Google TV with PatchWall",
            "Audio": "30W Dolby Audio speakers",
            "Ports": "3x HDMI, 2x USB, eARC",
            "Extras": "Built-in Chromecast, dual-band Wi-Fi",
            "Warranty": "1 year",
        },
        "rating": 4.3,
        "num_reviews": 14860,
        "stock": 8,
        "best_for": ["movies", "sports fans", "budget TV buyers"],
        "featured": False,
    },
    {
        "id": "PP-027",
        "name": "Fire-Boltt Ninja Call Pro Smartwatch",
        "category": "Electronics",
        "price_inr": 2199,
        "short_description": "Bluetooth-calling smartwatch with 1.69-inch display and 120 sports modes for under ₹2,500.",
        "description": "The Fire-Boltt Ninja Call Pro lets you take calls from your wrist thanks to its built-in speaker and mic, and tracks 120+ sports modes with heart-rate and SpO2 monitoring. The 1.69-inch HD display and IP67 rating make it easy daily wear.",
        "specs": {
            "Display": "1.69\" HD colour touch",
            "Calling": "Bluetooth calling, built-in mic & speaker",
            "Battery": "Up to 7 days",
            "Health": "Heart rate, SpO2, sleep tracking",
            "Sports modes": "120+",
            "Warranty": "1 year",
        },
        "rating": 4.0,
        "num_reviews": 41230,
        "stock": 60,
        "best_for": ["fitness beginners", "budget buyers", "gifts"],
        "featured": False,
    },
    {
        "id": "PP-028",
        "name": "Amazon Kindle Paperwhite (16 GB)",
        "category": "Electronics",
        "price_inr": 13999,
        "short_description": "Glare-free 6.8-inch e-reader with weeks of battery and waterproofing for serious readers.",
        "description": "The Kindle Paperwhite's 6.8-inch 300ppi E-Ink display reads like real paper in sunlight, with an adjustable warm light for night reading. It is IPX8 waterproof, holds thousands of books and lasts up to 10 weeks on a single charge.",
        "specs": {
            "Display": "6.8\" E-Ink, 300ppi, warm light",
            "Storage": "16GB (thousands of books)",
            "Battery": "Up to 10 weeks",
            "Waterproofing": "IPX8",
            "Extras": "Adjustable warm light, dark mode",
            "Warranty": "1 year",
        },
        "rating": 4.5,
        "num_reviews": 12410,
        "stock": 22,
        "best_for": ["readers", "students", "travel"],
        "featured": False,
    },
    # ----------------------------- Accessories ------------------------------
    {
        "id": "PP-029",
        "name": "Seagate Expansion 1TB Portable HDD",
        "category": "Accessories",
        "price_inr": 4499,
        "short_description": "Pocket-sized 1TB USB 3.0 drive for backups, projects and media libraries.",
        "description": "The Seagate Expansion Portable plugs into any computer over USB 3.0 with no external power supply, giving you 1TB of plug-and-play storage. Ideal for course backups, photo libraries and game archives.",
        "specs": {
            "Capacity": "1TB",
            "Interface": "USB 3.0 (backwards compatible)",
            "Form factor": "2.5\" portable, no external power",
            "Speed": "Up to 120 MB/s",
            "Compatibility": "Windows / Mac (reformat needed)",
            "Warranty": "1 year",
        },
        "rating": 4.4,
        "num_reviews": 9980,
        "stock": 45,
        "best_for": ["backups", "students", "photographers"],
        "featured": False,
    },
    {
        "id": "PP-030",
        "name": "Wildcraft 25L Everyday Backpack",
        "category": "Accessories",
        "price_inr": 1495,
        "short_description": "Water-resistant 25L backpack with a padded 15.6-inch sleeve for campus and travel.",
        "description": "The Wildcraft 25L everyday backpack carries a padded compartment that fits devices up to 15.6 inches, plus multiple organiser pockets and ergonomic air-mesh straps. Water-resistant polyester and sturdy zippers make it a campus favourite.",
        "specs": {
            "Capacity": "25L",
            "Sleeve": "Padded, fits up to 15.6\" devices",
            "Material": "Water-resistant polyester",
            "Comfort": "Air-mesh padded straps",
            "Pockets": "Multi-organiser + bottle pocket",
            "Warranty": "1 year",
        },
        "rating": 4.3,
        "num_reviews": 18760,
        "stock": 70,
        "best_for": ["students", "commuters", "travel"],
        "featured": False,
    },
    # ------------------------------- Fashion --------------------------------
    {
        "id": "PP-031",
        "name": "Fastrack UV-Protected Sunglasses",
        "category": "Fashion",
        "price_inr": 1995,
        "short_description": "UV400-protected wayfarer sunglasses with a lightweight polycarbonate frame.",
        "description": "Fastrack's wayfarer-style sunglasses pair UV400-protected lenses with a featherlight polycarbonate frame that survives daily wear. A versatile unisex look for commuting, biking and vacations.",
        "specs": {
            "Lens": "UV400 protection, anti-glare",
            "Frame": "Lightweight polycarbonate",
            "Style": "Wayfarer, unisex",
            "Fit": "Medium",
            "In the box": "Case + cleaning cloth",
            "Warranty": "6 months",
        },
        "rating": 4.1,
        "num_reviews": 6340,
        "stock": 55,
        "best_for": ["summer", "style", "everyday use"],
        "featured": False,
    },
    # --------------------------- Home & Lifestyle ---------------------------
    {
        "id": "PP-032",
        "name": "Philips HL7756 Mixer Grinder 750W",
        "category": "Home & Lifestyle",
        "price_inr": 3495,
        "short_description": "750W mixer grinder with three stainless-steel jars for everyday Indian cooking.",
        "description": "The Philips HL7756/01 uses a 750W motor with advanced air cooling for long grinding sessions, and its three leak-proof stainless-steel jars handle wet and dry grinding. A kitchen workhorse for dosa batter, chutneys and masalas.",
        "specs": {
            "Motor": "750W with advanced air cooling",
            "Jars": "3 stainless-steel jars, leak-proof lids",
            "Speed": "3 speeds + pulse",
            "Use cases": "Wet & dry grinding, chutney, batter",
            "Voltage": "230V",
            "Warranty": "2 years",
        },
        "rating": 4.3,
        "num_reviews": 21450,
        "stock": 18,
        "best_for": ["kitchen", "families", "everyday use"],
        "featured": False,
    },
    # ----------------------------- Fashion ----------------------------------
    {
        "id": "PP-033",
        "name": "U.S. Polo Assn. Men's Cotton Polo T-shirt",
        "category": "Fashion",
        "price_inr": 1299,
        "short_description": "Classic cotton piqué polo with the signature US Pony embroidery.",
        "description": "A wardrobe staple from U.S. Polo Assn. — breathable cotton piqué, ribbed collar and cuffs, and a two-button placket with the signature pony embroidery. Pairs as easily with chinos for smart-casual office days as with jeans on the weekend.",
        "specs": {
            "Fabric": "100% cotton piqué",
            "Fit": "Regular",
            "Sleeve": "Short sleeve",
            "Pattern": "Solid",
            "Care": "Machine wash",
            "Warranty": "Not applicable",
        },
        "rating": 4.1,
        "num_reviews": 5420,
        "stock": 60,
        "best_for": ["everyday wear", "college", "gifting"],
        "featured": False,
    },
    {
        "id": "PP-034",
        "name": "Woodland Men's Leather Boots",
        "category": "Fashion",
        "price_inr": 4299,
        "short_description": "Rugged full-grain leather trekking boots with anti-skid lug soles.",
        "description": "Woodland's cult-classic outdoor boots: a handcrafted full-grain leather upper that moulds to your feet, vulcanised rubber lug outsole for wet and uneven ground, and a cushioned insole for all-day wear. Built for monsoon streets and weekend treks alike.",
        "specs": {
            "Upper": "Full-grain leather",
            "Sole": "Vulcanised rubber lug outsole",
            "Closure": "Lace-up",
            "Water resistance": "Yes",
            "Care": "Polish regularly",
            "Warranty": "6 months",
        },
        "rating": 4.3,
        "num_reviews": 8910,
        "stock": 22,
        "best_for": ["outdoor", "winter", "everyday wear"],
        "featured": False,
    },
    {
        "id": "PP-035",
        "name": "H&M Oversized Denim Jacket",
        "category": "Fashion",
        "price_inr": 2999,
        "short_description": "Oversized light-wash denim jacket with button front and chest pockets.",
        "description": "An easy layering piece in washed indigo denim with a relaxed oversized fit, button front and four pockets. Throw it over a tee for evenings that turn cool, or under a coat when winter properly sets in.",
        "specs": {
            "Material": "100% cotton denim",
            "Fit": "Oversized",
            "Wash": "Light-wash indigo",
            "Closure": "Button front",
            "Pockets": "2 chest, 2 side",
            "Care": "Machine wash cold",
        },
        "rating": 4.2,
        "num_reviews": 2140,
        "stock": 35,
        "best_for": ["layering", "everyday wear", "college"],
        "featured": False,
    },
    # -------------------------- Home & Lifestyle ----------------------------
    {
        "id": "PP-036",
        "name": "Pigeon Favourite Electric Kettle 1.5L",
        "category": "Home & Lifestyle",
        "price_inr": 699,
        "short_description": "1.5L stainless-steel kettle with auto cut-off — boils water in ~5 minutes.",
        "description": "The Pigeon Favourite is India's go-to budget kettle: a 1.5L stainless-steel body, 1500W concealed element that boils a full kettle in about five minutes, and automatic shut-off with boil-dry protection. A hostel and office-desk essential.",
        "specs": {
            "Capacity": "1.5 L",
            "Material": "Stainless steel",
            "Power": "1500W concealed element",
            "Safety": "Auto cut-off, boil-dry protection",
            "Warranty": "1 year",
        },
        "rating": 4.0,
        "num_reviews": 48230,
        "stock": 120,
        "best_for": ["budget buys", "students", "travel"],
        "featured": False,
    },
    {
        "id": "PP-037",
        "name": "Instant Vortex 4L Air Fryer",
        "category": "Home & Lifestyle",
        "price_inr": 8999,
        "short_description": "4-litre digital air fryer with one-touch programmes and 60-minute timer.",
        "description": "The Instant Vortex makes fried food with up to 95% less oil: a 4-litre basket, four one-touch smart programmes (air fry, roast, bake, reheat) and a 60-minute timer with auto shut-off. From frozen fries to reheating biryani without sogginess, it earns its counter space.",
        "specs": {
            "Capacity": "4 L",
            "Power": "1400W",
            "Controls": "Digital touch panel",
            "Programmes": "Air fry, roast, bake, reheat",
            "Timer": "60 minutes, auto shut-off",
            "Warranty": "1 year",
        },
        "rating": 4.3,
        "num_reviews": 11200,
        "stock": 28,
        "best_for": ["healthy cooking", "families", "gifting"],
        "featured": False,
    },
    {
        "id": "PP-038",
        "name": "Wakefit Orthopaedic Memory Foam Mattress (Queen)",
        "category": "Home & Lifestyle",
        "price_inr": 11999,
        "short_description": "Queen-size orthopaedic memory foam mattress with 100-night trial.",
        "description": "Wakefit's orthopaedic mattress layers memory foam over high-density support foam to hold your spine neutral while softening pressure points — a medium-firm feel back-pain sufferers usually settle on. Ships vacuum-rolled, expands in a few hours, and comes with a 100-night trial.",
        "specs": {
            "Size": "78 x 60 in (Queen)",
            "Thickness": "6 in",
            "Material": "Memory foam + HR foam",
            "Firmness": "Medium-firm",
            "Trial": "100 nights",
            "Warranty": "10 years",
        },
        "rating": 4.4,
        "num_reviews": 26890,
        "stock": 15,
        "best_for": ["back pain relief", "couples", "bedrooms"],
        "featured": True,
    },
    # ----------------------------- Accessories ------------------------------
    {
        "id": "PP-039",
        "name": "SanDisk Ultra 128GB microSDXC Card",
        "category": "Accessories",
        "price_inr": 1099,
        "short_description": "Class 10 UHS-I card at up to 120MB/s, with full-size SD adapter.",
        "description": "The SanDisk Ultra 128GB microSDXC moves photos and videos off your phone at up to 120MB/s and is rated Class 10 / UHS-I for Full HD recording. A full-size SD adapter is included, so it slots into your action cam or DSLR as easily as your phone.",
        "specs": {
            "Capacity": "128 GB",
            "Read speed": "Up to 120 MB/s",
            "Class": "Class 10, UHS-I",
            "Adapter": "Full-size SD included",
            "Ideal for": "Smartphones, action cams",
            "Warranty": "10 years",
        },
        "rating": 4.4,
        "num_reviews": 65410,
        "stock": 200,
        "best_for": ["budget buys", "photography", "everyday use"],
        "featured": False,
    },
    {
        "id": "PP-040",
        "name": "Logitech B170 Wireless Mouse",
        "category": "Accessories",
        "price_inr": 699,
        "short_description": "Compact 2.4GHz wireless mouse with 12-month AA battery life.",
        "description": "The B170 is the default office mouse for a reason: plug the tiny nano receiver in and forget it, enjoy a contoured ambidextrous shape, and run a full year on one AA battery. 1000 DPI tracking works on desks, mousepads and the occasional chair arm.",
        "specs": {
            "Connectivity": "2.4 GHz USB nano receiver",
            "DPI": "1000",
            "Battery": "1 AA, up to 12 months",
            "Buttons": "3",
            "Range": "10 m",
            "Warranty": "3 years",
        },
        "rating": 4.2,
        "num_reviews": 34200,
        "stock": 150,
        "best_for": ["work from home", "students", "budget buys"],
        "featured": False,
    },
    # ----------------------------- Electronics ------------------------------
    {
        "id": "PP-041",
        "name": "Apple iPad (10th Gen) 64GB WiFi",
        "category": "Electronics",
        "price_inr": 34900,
        "short_description": "10.9-inch Liquid Retina iPad with A14 Bionic and all-day battery.",
        "description": "The 10th-generation iPad pairs a 10.9-inch Liquid Retina display with the A14 Bionic chip — fast enough for note-taking, streaming and light editing, with up to 10 hours of battery. The front camera sits on the landscape edge, finally, making video calls natural.",
        "specs": {
            "Display": "10.9\" Liquid Retina",
            "Chip": "A14 Bionic",
            "Storage": "64 GB",
            "Camera": "12MP wide, 12MP landscape front",
            "Battery": "Up to 10 hours",
            "Warranty": "1 year",
        },
        "rating": 4.6,
        "num_reviews": 9140,
        "stock": 20,
        "best_for": ["students", "entertainment", "note-taking"],
        "featured": False,
    },
    {
        "id": "PP-042",
        "name": "Sony PlayStation 5 Slim (Digital Edition)",
        "category": "Electronics",
        "price_inr": 44990,
        "short_description": "The slimmer PS5 Digital Edition with a 1TB SSD and DualSense controller.",
        "description": "The PS5 Slim Digital Edition packs the same custom RDNA 2 CPU/GPU as the original into a 30% smaller body, with a 1TB SSD for your game library. The DualSense controller's haptics and adaptive triggers are still the best way to feel a game, from Astro Bot to EA FC.",
        "specs": {
            "Storage": "1 TB SSD",
            "Output": "4K up to 120Hz, 8K ready",
            "Controller": "DualSense haptic + adaptive triggers",
            "Drive": "None (digital edition)",
            "Warranty": "1 year",
        },
        "rating": 4.7,
        "num_reviews": 15480,
        "stock": 12,
        "best_for": ["gaming", "entertainment", "gifting"],
        "featured": True,
    },
    # ----------------------------- Smartphones -----------------------------
    {
        "id": "PP-043",
        "name": "Apple iPhone 15 (128GB)",
        "category": "Smartphones",
        "price_inr": 62900,
        "short_description": "A16-powered iPhone with Dynamic Island, USB-C and a 48MP camera.",
        "description": "The iPhone 15 moves to USB-C and pairs the A16 Bionic with a 48MP main camera and Dynamic Island. Ceramic Shield glass, a colour-infused aluminium body and five-plus years of iOS updates make it the safe premium pick.",
        "specs": {
            "Display": "6.1\" Super Retina XDR OLED",
            "Chip": "A16 Bionic",
            "Storage": "128 GB",
            "Camera": "48MP + 12MP ultrawide, 12MP front",
            "Battery": "Up to 20 hours video",
            "Warranty": "1 year",
        },
        "rating": 4.6,
        "num_reviews": 22400,
        "stock": 15,
        "best_for": ["everyday use", "photography", "gifting"],
        "featured": False,
    },
    {
        "id": "PP-044",
        "name": "Samsung Galaxy S24 5G",
        "category": "Smartphones",
        "price_inr": 49999,
        "short_description": "Compact flagship with Galaxy AI and a 2600-nit 120Hz AMOLED.",
        "description": "The Galaxy S24 keeps the compact flagship alive: a 6.2-inch 120Hz AMOLED that peaks at 2600 nits, the Snapdragon 8 Gen 3 for Galaxy, and Galaxy AI tools like Circle to Search and live call translation. Seven years of updates seal the deal.",
        "specs": {
            "Display": "6.2\" Dynamic AMOLED 2X, 120Hz",
            "Processor": "Snapdragon 8 Gen 3",
            "RAM / Storage": "8GB / 256GB",
            "Camera": "50MP OIS + 12MP + 10MP tele, 12MP front",
            "Battery": "4000mAh, 25W",
            "Warranty": "1 year",
        },
        "rating": 4.5,
        "num_reviews": 15800,
        "stock": 20,
        "best_for": ["power users", "photography", "everyday use"],
        "featured": False,
    },
    {
        "id": "PP-045",
        "name": "Motorola G64 5G",
        "category": "Smartphones",
        "price_inr": 13999,
        "short_description": "6000mAh battery, 120Hz display and bloat-free Android on a budget.",
        "description": "The moto g64 packs a 6000mAh battery that comfortably runs two days, a 120Hz display and the Dimensity 7025 chip. Bloat-free Android stays quick long after other budget skins start to stutter.",
        "specs": {
            "Display": "6.5\" IPS, 120Hz",
            "Processor": "Dimensity 7025",
            "RAM / Storage": "8GB / 128GB",
            "Camera": "50MP OIS + 8MP ultrawide, 16MP front",
            "Battery": "6000mAh, 33W",
            "Warranty": "1 year",
        },
        "rating": 4.2,
        "num_reviews": 31200,
        "stock": 65,
        "best_for": ["budget buys", "students", "everyday use"],
        "featured": False,
    },
    {
        "id": "PP-046",
        "name": "iQOO Z9 5G",
        "category": "Smartphones",
        "price_inr": 18499,
        "short_description": "Gaming-focused mid-ranger with a 120Hz AMOLED and 80W charging.",
        "description": "The iQOO Z9 pairs a 120Hz AMOLED with the Dimensity 7200 and a large vapour chamber for sustained gaming sessions. 80W FlashCharge tops up the 5000mAh cell well within an hour.",
        "specs": {
            "Display": "6.67\" AMOLED, 120Hz",
            "Processor": "Dimensity 7200",
            "RAM / Storage": "8GB / 128GB",
            "Camera": "50MP OIS + 2MP, 16MP front",
            "Battery": "5000mAh, 80W",
            "Warranty": "1 year",
        },
        "rating": 4.3,
        "num_reviews": 18900,
        "stock": 40,
        "best_for": ["gaming", "students", "budget buyers"],
        "featured": False,
    },
    # ------------------------------- Laptops --------------------------------
    {
        "id": "PP-047",
        "name": "Apple MacBook Air M3 13-inch",
        "category": "Laptops",
        "price_inr": 94900,
        "short_description": "Fanless M3 thin-and-light with an 18-hour battery in a 1.24 kg body.",
        "description": "The M3 MacBook Air stays silent under load, drives two external displays with the lid open and still delivers all-day battery in a 1.24 kg wedge. The 13.6-inch Liquid Retina display and hardware-accelerated ray tracing make it the default thin-and-light.",
        "specs": {
            "Display": "13.6\" Liquid Retina, 500 nits",
            "Chip": "Apple M3",
            "RAM / Storage": "8GB / 256GB SSD",
            "Camera": "1080p FaceTime HD",
            "Battery": "Up to 18 hours",
            "Warranty": "1 year",
        },
        "rating": 4.7,
        "num_reviews": 7600,
        "stock": 12,
        "best_for": ["power users", "students", "work from home"],
        "featured": False,
    },
    {
        "id": "PP-048",
        "name": "ASUS Vivobook 15 (Ryzen 5)",
        "category": "Laptops",
        "price_inr": 49990,
        "short_description": "Thin 15-inch Ryzen 5 machine with 16GB RAM and a backlit keyboard.",
        "description": "The Vivobook 15 balances a Ryzen 5 7530U, 16GB of RAM and a fast 512GB SSD in a 1.7 kg body — plenty for spreadsheets, coding classes and forty browser tabs. A backlit keyboard and a physical webcam shutter round it out.",
        "specs": {
            "Display": "15.6\" FHD, 60Hz",
            "Processor": "AMD Ryzen 5 7530U",
            "RAM / Storage": "16GB / 512GB SSD",
            "Graphics": "Integrated Radeon",
            "Battery": "42Wh, ~6 hours",
            "Warranty": "1 year",
        },
        "rating": 4.3,
        "num_reviews": 6800,
        "stock": 30,
        "best_for": ["students", "office", "everyday use"],
        "featured": False,
    },
    {
        "id": "PP-049",
        "name": "Lenovo V14 (Ryzen 5)",
        "category": "Laptops",
        "price_inr": 36990,
        "short_description": "No-nonsense 14-inch workhorse for classes and daily office work.",
        "description": "The V14 is the classic dependable workhorse: a Ryzen 5 7520U, 8GB RAM and a 512GB SSD in a matte 14-inch chassis that shrugs off backpack life. Dual-band Wi-Fi and a full set of ports keep you connected without dongles.",
        "specs": {
            "Display": "14\" FHD, anti-glare",
            "Processor": "AMD Ryzen 5 7520U",
            "RAM / Storage": "8GB / 512GB SSD",
            "Graphics": "Integrated Radeon",
            "Battery": "38Wh, ~7 hours",
            "Warranty": "1 year",
        },
        "rating": 4.1,
        "num_reviews": 4200,
        "stock": 45,
        "best_for": ["students", "office", "budget buys"],
        "featured": False,
    },
    # ------------------------------ Electronics -----------------------------
    {
        "id": "PP-050",
        "name": "Samsung Galaxy Tab S6 Lite",
        "category": "Electronics",
        "price_inr": 17999,
        "short_description": "10.4-inch tablet with the S Pen in the box for notes and sketches.",
        "description": "The Tab S6 Lite remains the value pick for stylus users: the S Pen is included, slots into the chassis and never needs charging. Samsung Notes handles lectures and meetings, and the Exynos 1280 keeps multitasking smooth.",
        "specs": {
            "Display": "10.4\" TFT, 2000 x 1200",
            "Processor": "Exynos 1280",
            "RAM / Storage": "4GB / 64GB (microSD)",
            "S Pen": "Included",
            "Battery": "7040mAh",
            "Warranty": "1 year",
        },
        "rating": 4.4,
        "num_reviews": 12300,
        "stock": 25,
        "best_for": ["students", "note-taking", "entertainment"],
        "featured": False,
    },
    {
        "id": "PP-051",
        "name": "Sony Bravia 55\" 4K Google TV",
        "category": "Electronics",
        "price_inr": 61990,
        "short_description": "55-inch 4K HDR Google TV with Sony's X-Reality PRO processing.",
        "description": "The Bravia 55-incher pairs a 4K HDR panel with Sony's X-Reality PRO upscaling — old cable feeds and streaming alike look cleaner than they have any right to. Google TV, Dolby Audio and two 20W speakers complete the living-room package.",
        "specs": {
            "Display": "55\" 4K UHD LED",
            "HDR": "HDR10, HLG",
            "OS": "Google TV",
            "Audio": "2 x 20W, Dolby Audio",
            "Ports": "3 HDMI, 2 USB",
            "Warranty": "1 year",
        },
        "rating": 4.5,
        "num_reviews": 8900,
        "stock": 14,
        "best_for": ["entertainment", "families", "gifting"],
        "featured": False,
    },
    {
        "id": "PP-052",
        "name": "JBL Bar 300 Soundbar",
        "category": "Electronics",
        "price_inr": 27999,
        "short_description": "5.0-channel Dolby Atmos soundbar with built-in Chromecast.",
        "description": "The Bar 300 delivers 260W of room-filling Dolby Atmos sound without a subwoofer to hide — 5.0 channels, HDMI eARC, and Chromecast built in for streaming music straight from your phone.",
        "specs": {
            "Channels": "5.0",
            "Power": "260W total",
            "Dolby": "Atmos",
            "Connectivity": "HDMI eARC, optical, Bluetooth",
            "Streaming": "Chromecast built-in",
            "Warranty": "1 year",
        },
        "rating": 4.4,
        "num_reviews": 5600,
        "stock": 18,
        "best_for": ["entertainment", "home theatre", "families"],
        "featured": False,
    },
    {
        "id": "PP-053",
        "name": "Canon EOS R50 Mirrorless Camera",
        "category": "Electronics",
        "price_inr": 64990,
        "short_description": "24MP APS-C mirrorless with 4K video and Dual Pixel autofocus.",
        "description": "The EOS R50 is Canon's friendliest mirrorless: a 24.2MP APS-C sensor, Dual Pixel CMOS AF II that sticks to eyes like glue, and uncropped 4K30 video. At 375 g with the 18-45mm kit lens, it travels light.",
        "specs": {
            "Sensor": "24.2MP APS-C",
            "Video": "4K 30p, FHD 120p",
            "Autofocus": "Dual Pixel CMOS AF II",
            "Lens": "RF-S 18-45mm kit lens",
            "Weight": "375 g with battery",
            "Warranty": "1 year",
        },
        "rating": 4.6,
        "num_reviews": 3800,
        "stock": 10,
        "best_for": ["photography", "content creation", "travel"],
        "featured": False,
    },
    {
        "id": "PP-054",
        "name": "boAt Rockerz 550 Over-Ear Headphones",
        "category": "Electronics",
        "price_inr": 1999,
        "short_description": "50mm drivers, 20-hour battery and plush over-ear cushions.",
        "description": "The Rockerz 550 do the basics well: big 50mm drivers with surprisingly decent bass, 20 hours of playback, Bluetooth 5.0 and physical playback controls on the earcup. The plush cushions make long listening sessions easy.",
        "specs": {
            "Drivers": "50mm dynamic",
            "Battery": "20 hours",
            "Bluetooth": "5.0",
            "Extras": "microSD slot, AUX",
            "Weight": "220 g",
            "Warranty": "1 year",
        },
        "rating": 4.1,
        "num_reviews": 48600,
        "stock": 85,
        "best_for": ["budget buys", "everyday use", "entertainment"],
        "featured": False,
    },
    # ----------------------------- Accessories ------------------------------
    {
        "id": "PP-055",
        "name": "Lenovo 130 Wireless Mouse",
        "category": "Accessories",
        "price_inr": 649,
        "short_description": "Plug-and-play 2.4GHz mouse with 12-month battery life.",
        "description": "The 130 is the office workhorse: plug the tiny nano receiver and go, with a 1000 DPI sensor, three buttons and a curved shell that suits either hand. One AA battery lasts about a year.",
        "specs": {
            "Connectivity": "2.4 GHz nano receiver",
            "DPI": "1000",
            "Battery": "1 AA, ~12 months",
            "Buttons": "3",
            "Design": "Ambidextrous",
            "Warranty": "1 year",
        },
        "rating": 4.1,
        "num_reviews": 21400,
        "stock": 140,
        "best_for": ["work from home", "students", "budget buys"],
        "featured": False,
    },
    {
        "id": "PP-056",
        "name": "Portronics My Buddy D Adjustable Stand",
        "category": "Accessories",
        "price_inr": 1099,
        "short_description": "Aluminium riser that props your screen to eye level and folds flat.",
        "description": "My Buddy D lifts your screen to eye level with six lockable angles, improves airflow around your machine and folds flat for the backpack. Rubber pads keep both the device and the desk scratch-free.",
        "specs": {
            "Material": "Aluminium alloy",
            "Angles": "6 lockable positions",
            "Compatibility": "10-17 inch screens",
            "Folded": "2 cm flat",
            "Extras": "Rubber pads",
            "Warranty": "6 months",
        },
        "rating": 4.2,
        "num_reviews": 15700,
        "stock": 90,
        "best_for": ["work from home", "students", "office"],
        "featured": False,
    },
    {
        "id": "PP-057",
        "name": "Anker 555 USB-C Hub (8-in-1)",
        "category": "Accessories",
        "price_inr": 3299,
        "short_description": "Eight ports — dual HDMI, ethernet, card slots and 100W passthrough.",
        "description": "The 555 turns one USB-C port into a whole desk: dual 4K HDMI outputs, gigabit ethernet, SD and microSD slots, three USB-A ports and 100W passthrough charging. An aluminium shell, and no drivers needed.",
        "specs": {
            "Ports": "2 HDMI, 3 USB-A, 1 USB-C PD",
            "Ethernet": "Gigabit",
            "Card slots": "SD + microSD",
            "Passthrough": "100W",
            "Video": "Dual 4K @ 30Hz",
            "Warranty": "18 months",
        },
        "rating": 4.4,
        "num_reviews": 9800,
        "stock": 35,
        "best_for": ["work from home", "power users", "office"],
        "featured": False,
    },
    {
        "id": "PP-058",
        "name": "Logitech C270 HD Webcam",
        "category": "Accessories",
        "price_inr": 1795,
        "short_description": "720p webcam with noise-reducing mic and auto light correction.",
        "description": "The C270 is the default video-call camera: 720p at 30fps, a noise-reducing mic and auto light correction that rescues dim rooms. The universal clip grips panels and tripods alike.",
        "specs": {
            "Video": "720p HD @ 30fps",
            "Microphone": "Noise reducing",
            "Field of view": "60°",
            "Mount": "Universal clip",
            "Cable": "1.5 m",
            "Warranty": "2 years",
        },
        "rating": 4.2,
        "num_reviews": 27800,
        "stock": 60,
        "best_for": ["work from home", "students", "online classes"],
        "featured": False,
    },
    {
        "id": "PP-059",
        "name": "Samsung T7 Shield 1TB Portable SSD",
        "category": "Accessories",
        "price_inr": 8499,
        "short_description": "1,050MB/s rugged SSD that shrugs off drops and rain.",
        "description": "The T7 Shield moves files at up to 1,050MB/s over USB 3.2 Gen 2, with a rubberised shell rated for 3-metre drops and IP65 dust-and-water resistance. Pocket-sized, password-protectable and it works with everything.",
        "specs": {
            "Capacity": "1 TB",
            "Read speed": "Up to 1,050 MB/s",
            "Interface": "USB 3.2 Gen 2 Type-C",
            "Durability": "IP65, 3 m drop rated",
            "Security": "Password protection (AES 256)",
            "Warranty": "3 years",
        },
        "rating": 4.7,
        "num_reviews": 11200,
        "stock": 28,
        "best_for": ["work from home", "photography", "gaming"],
        "featured": False,
    },
    {
        "id": "PP-060",
        "name": "boAt Airdopes 311 Pro TWS Earbuds",
        "category": "Accessories",
        "price_inr": 1199,
        "short_description": "TWS earbuds with 50-hour case battery and low-latency gaming mode.",
        "description": "The Airdopes 311 Pro stretch to 50 hours of playback with the case, charge over USB-C and switch into a low-latency BEAST mode for gaming. IPX4 sweat resistance makes them gym-ready.",
        "specs": {
            "Playback": "Up to 50 hours (with case)",
            "Drivers": "13mm dynamic",
            "Bluetooth": "5.3",
            "Water resistance": "IPX4",
            "Charging": "USB-C",
            "Warranty": "1 year",
        },
        "rating": 4.0,
        "num_reviews": 62300,
        "stock": 110,
        "best_for": ["budget buys", "gym", "everyday use"],
        "featured": False,
    },
    {
        "id": "PP-061",
        "name": "American Tourister 55cm Cabin Trolley",
        "category": "Accessories",
        "price_inr": 2799,
        "short_description": "Cabin-size hard-side trolley with TSA lock and spinner wheels.",
        "description": "This 55cm polycarbonate shell fits most domestic cabin rules, rolls on four 360° spinner wheels and locks with a built-in TSA combination lock. A weekend's clothes, shoes and toiletries fit with room to spare.",
        "specs": {
            "Size": "55 cm, ~34 L",
            "Shell": "Polycarbonate",
            "Wheels": "4 x 360° spinners",
            "Lock": "TSA combination",
            "Weight": "2.6 kg",
            "Warranty": "3 years",
        },
        "rating": 4.2,
        "num_reviews": 17900,
        "stock": 50,
        "best_for": ["travel", "weekend trips", "gifting"],
        "featured": False,
    },
    {
        "id": "PP-062",
        "name": "HP v236w 64GB Pen Drive",
        "category": "Accessories",
        "price_inr": 499,
        "short_description": "64GB USB 2.0 pen drive in a cap-protected metal body.",
        "description": "The v236w is the humble desk-drawer staple: 64GB of plug-and-play storage in a cap-protected metal shell, with a strap hole for keychains. Fine for documents, photos and bootable installers.",
        "specs": {
            "Capacity": "64 GB",
            "Interface": "USB 2.0",
            "Body": "Metal",
            "Read speed": "Up to 30 MB/s",
            "Warranty": "2 years",
        },
        "rating": 4.1,
        "num_reviews": 55100,
        "stock": 200,
        "best_for": ["budget buys", "students", "everyday use"],
        "featured": False,
    },
    # ------------------------------- Fashion --------------------------------
    {
        "id": "PP-063",
        "name": "Puma Solid Men's T-shirt",
        "category": "Fashion",
        "price_inr": 999,
        "short_description": "Pure cotton crew-neck tee with the Puma logo at the chest.",
        "description": "A regular-fit cotton tee built for the daily rotation: soft single-jersey knit that keeps its shape wash after wash, with a small Puma logo that keeps it from looking plain.",
        "specs": {
            "Fabric": "100% cotton",
            "Fit": "Regular",
            "Neck": "Crew",
            "Sleeve": "Short",
            "Care": "Machine wash",
            "Warranty": "Not applicable",
        },
        "rating": 4.1,
        "num_reviews": 12600,
        "stock": 120,
        "best_for": ["everyday wear", "college", "gym"],
        "featured": False,
    },
    {
        "id": "PP-064",
        "name": "Allen Solly Casual Shirt",
        "category": "Fashion",
        "price_inr": 1499,
        "short_description": "Slim-fit cotton casual shirt with a contemporary spread collar.",
        "description": "Allen Solly's casual line makes office-to-evening easy: a breathable cotton weave, a slim-but-not-tight cut, and shades that pair with chinos and denim alike.",
        "specs": {
            "Fabric": "Cotton",
            "Fit": "Slim",
            "Collar": "Spread",
            "Sleeves": "Full sleeve",
            "Care": "Machine wash",
            "Warranty": "Not applicable",
        },
        "rating": 4.2,
        "num_reviews": 6900,
        "stock": 70,
        "best_for": ["office", "everyday wear", "gifting"],
        "featured": False,
    },
    {
        "id": "PP-065",
        "name": "Roadster Women's Printed Kurti",
        "category": "Fashion",
        "price_inr": 749,
        "short_description": "Straight-cut printed kurti in soft rayon with three-quarter sleeves.",
        "description": "A straight-cut rayon kurti that breathes through Indian summers: an all-over print, three-quarter sleeves and side slits that make long days easy. Dress it up with jhumkas or down with leggings.",
        "specs": {
            "Fabric": "Rayon",
            "Fit": "Straight",
            "Sleeves": "Three-quarter",
            "Length": "Calf length",
            "Care": "Machine wash cold",
            "Warranty": "Not applicable",
        },
        "rating": 4.0,
        "num_reviews": 18700,
        "stock": 100,
        "best_for": ["everyday wear", "college", "office"],
        "featured": False,
    },
    {
        "id": "PP-066",
        "name": "Levi's Women's 311 Shaping Jeans",
        "category": "Fashion",
        "price_inr": 2499,
        "short_description": "Mid-rise skinny jeans in sculpting four-way stretch denim.",
        "description": "The 311 sits at the natural waist and skims to the ankle, with four-way stretch that keeps its shape through a full day. The dark indigo wash works with sneakers and boots alike.",
        "specs": {
            "Fit": "Skinny",
            "Rise": "Mid-rise",
            "Fabric": "Stretch denim",
            "Closure": "Zip fly, button",
            "Care": "Machine wash cold",
            "Warranty": "Not applicable",
        },
        "rating": 4.2,
        "num_reviews": 8400,
        "stock": 55,
        "best_for": ["everyday wear", "college", "office"],
        "featured": False,
    },
    {
        "id": "PP-067",
        "name": "Bata Remo Men's Formal Derby Shoes",
        "category": "Fashion",
        "price_inr": 1799,
        "short_description": "Genuine leather derbies with cushioned insoles for long days.",
        "description": "The Remo is Bata's dependable formal: a genuine leather upper, a lace-up closure and a cushioned footbed that survives full days on your feet. The dark tan finish suits both trousers and dark denim.",
        "specs": {
            "Upper": "Genuine leather",
            "Sole": "TPR",
            "Closure": "Lace-up",
            "Occasion": "Formal / office",
            "Care": "Polish regularly",
            "Warranty": "3 months",
        },
        "rating": 4.1,
        "num_reviews": 9300,
        "stock": 48,
        "best_for": ["office", "formal wear", "gifting"],
        "featured": False,
    },
    {
        "id": "PP-068",
        "name": "Nike Court Vision Low Sneakers",
        "category": "Fashion",
        "price_inr": 4495,
        "short_description": "Court-inspired leather sneakers with a clean retro silhouette.",
        "description": "The Court Vision Low borrows its lines from 80s basketball: a leather upper, a perforated toe and a cupsole that doubles for courts and campuses. The white-cream colourway goes with almost everything.",
        "specs": {
            "Upper": "Leather",
            "Fit": "True to size",
            "Closure": "Lace-up",
            "Use": "Casual / courts",
            "Care": "Wipe clean",
            "Warranty": "Not applicable",
        },
        "rating": 4.3,
        "num_reviews": 7100,
        "stock": 40,
        "best_for": ["everyday wear", "college", "gym"],
        "featured": False,
    },
    {
        "id": "PP-069",
        "name": "Casio F91W-1 Digital Watch",
        "category": "Fashion",
        "price_inr": 1095,
        "short_description": "The indestructible classic: 30m water resistance, 7-year battery.",
        "description": "Casio's F91W has outlived four decades of trends: a featherweight resin strap, a crisp digital face with stopwatch and alarm, a 7-year battery and 30m water resistance. It weighs almost nothing and costs less than dinner.",
        "specs": {
            "Movement": "Digital quartz",
            "Case": "Resin, 35mm",
            "Water resistance": "30m",
            "Battery": "~7 years (CR2016)",
            "Features": "Stopwatch, alarm, backlight",
            "Warranty": "1 year",
        },
        "rating": 4.6,
        "num_reviews": 34500,
        "stock": 90,
        "best_for": ["everyday wear", "budget buys", "gifting"],
        "featured": False,
    },
    {
        "id": "PP-070",
        "name": "Fossil Commuter Chronograph Watch",
        "category": "Fashion",
        "price_inr": 8995,
        "short_description": "Stainless-steel chronograph with a navy sunray dial.",
        "description": "The Commuter is Fossil at its polished best: a 42mm steel case, a sunray navy dial with three chronograph sub-dials and 5 ATM water resistance. It slides under a cuff but earns second glances.",
        "specs": {
            "Movement": "Chronograph quartz",
            "Case": "Stainless steel, 42mm",
            "Dial": "Navy sunray",
            "Water resistance": "5 ATM",
            "Strap": "Steel bracelet",
            "Warranty": "2 years",
        },
        "rating": 4.4,
        "num_reviews": 5200,
        "stock": 20,
        "best_for": ["office", "formal wear", "gifting"],
        "featured": False,
    },
    {
        "id": "PP-071",
        "name": "Louis Philippe Leather Belt",
        "category": "Fashion",
        "price_inr": 999,
        "short_description": "Full-grain leather formal belt with a brushed buckle.",
        "description": "A full-grain leather belt from Louis Philippe with a brushed single-prong buckle — the 35mm width suits formal trousers and dark denim equally. Cut-to-fit sizing keeps the fit simple.",
        "specs": {
            "Material": "Full-grain leather",
            "Buckle": "Brushed metal",
            "Width": "35 mm",
            "Sizing": "Cut to fit",
            "Occasion": "Formal / smart casual",
            "Warranty": "6 months",
        },
        "rating": 4.2,
        "num_reviews": 11800,
        "stock": 80,
        "best_for": ["office", "formal wear", "gifting"],
        "featured": False,
    },
    # -------------------------- Home & Lifestyle ----------------------------
    {
        "id": "PP-072",
        "name": "Bombay Dyeing Cotton Double Bedsheet",
        "category": "Home & Lifestyle",
        "price_inr": 999,
        "short_description": "Soft cotton double bedsheet with two matching pillow covers.",
        "description": "A high-count cotton double bedsheet that washes soft and stays soft: a clean stripe print, fade-resistant dyes and two matching pillow covers in the set. Fits standard double mattresses.",
        "specs": {
            "Size": "Double bed",
            "Fabric": "Cotton, 210 TC",
            "Includes": "2 pillow covers",
            "Pattern": "Striped",
            "Care": "Machine wash",
            "Warranty": "Not applicable",
        },
        "rating": 4.2,
        "num_reviews": 22300,
        "stock": 75,
        "best_for": ["bedrooms", "families", "everyday use"],
        "featured": False,
    },
    {
        "id": "PP-073",
        "name": "Hawkins Contura Pressure Cooker 3L",
        "category": "Home & Lifestyle",
        "price_inr": 2399,
        "short_description": "Hard-anodised 3L cooker with a curved body for easy stirring.",
        "description": "The Contura's curved interior lets you stir and brown onions right in the cooker before closing the lid — no separate kadai for the masala. Hard-anodised body, inside-fitting lid, and Hawkins' long service network.",
        "specs": {
            "Capacity": "3 L",
            "Body": "Hard-anodised aluminium",
            "Lid": "Inside fitting",
            "Induction ready": "Yes",
            "Warranty": "5 years",
        },
        "rating": 4.5,
        "num_reviews": 16400,
        "stock": 33,
        "best_for": ["kitchen", "families", "everyday use"],
        "featured": False,
    },
    {
        "id": "PP-074",
        "name": "Larah by Borosil Dinner Set (20 pcs)",
        "category": "Home & Lifestyle",
        "price_inr": 1999,
        "short_description": "20-piece opalware dinner set — microwave and dishwasher safe.",
        "description": "Larah's opalware is chip-resistant, feather-light and stacks small. This 20-piece set services a family of four twice over — dinner plates, quarter plates and katori bowls — moving from microwave to table to dishwasher.",
        "specs": {
            "Pieces": "20 (service for 4)",
            "Material": "Opal ware",
            "Microwave safe": "Yes",
            "Dishwasher safe": "Yes",
            "Pattern": "Contemporary floral",
            "Warranty": "Not applicable",
        },
        "rating": 4.3,
        "num_reviews": 14200,
        "stock": 42,
        "best_for": ["kitchen", "families", "gifting"],
        "featured": False,
    },
    {
        "id": "PP-075",
        "name": "Wipro Garnet LED Table Lamp",
        "category": "Home & Lifestyle",
        "price_inr": 699,
        "short_description": "Adjustable study lamp with three brightness levels and USB power.",
        "description": "The Garnet throws even, flicker-free light across a study table and bends where you point it. Three touch-controlled brightness levels and USB power keep desks tidy and eyes comfortable.",
        "specs": {
            "Light": "LED, flicker-free",
            "Brightness": "3 levels",
            "Power": "5V USB",
            "Head": "Adjustable",
            "Body": "Plastic + metal",
            "Warranty": "1 year",
        },
        "rating": 4.1,
        "num_reviews": 7900,
        "stock": 65,
        "best_for": ["students", "bedrooms", "office"],
        "featured": False,
    },
    {
        "id": "PP-076",
        "name": "Ajanta Round Wall Clock (30cm)",
        "category": "Home & Lifestyle",
        "price_inr": 649,
        "short_description": "Silent-sweep 30cm wall clock with a bold, readable dial.",
        "description": "Ajanta's 30cm dial is legible from across the room, and the silent-sweep movement means no ticking in quiet rooms and light sleepers. Runs about a year on a single AA cell.",
        "specs": {
            "Diameter": "30 cm",
            "Movement": "Silent sweep quartz",
            "Power": "1 x AA",
            "Dial": "Bold numerals",
            "Frame": "Plastic",
            "Warranty": "1 year",
        },
        "rating": 4.2,
        "num_reviews": 13600,
        "stock": 90,
        "best_for": ["bedrooms", "office", "everyday use"],
        "featured": False,
    },
    {
        "id": "PP-077",
        "name": "Vinod Triply Stainless Steel Kadai (24cm)",
        "category": "Home & Lifestyle",
        "price_inr": 1599,
        "short_description": "Triply kadai — steel body, aluminium core, induction ready.",
        "description": "Vinod's triply construction sandwiches an aluminium core between steel layers, so the kadai heats fast and evenly without hot spots — and the steel surface doesn't react with tangy curries. Works on induction and gas alike.",
        "specs": {
            "Diameter": "24 cm",
            "Construction": "Triply (SS-Al-SS)",
            "Base": "Induction ready",
            "Capacity": "~3.5 L",
            "Handles": "Riveted steel",
            "Warranty": "1 year",
        },
        "rating": 4.4,
        "num_reviews": 6300,
        "stock": 38,
        "best_for": ["kitchen", "families", "healthy cooking"],
        "featured": False,
    },
    {
        "id": "PP-078",
        "name": "Nilkamal Solid Armchair",
        "category": "Home & Lifestyle",
        "price_inr": 1099,
        "short_description": "Weatherproof moulded armchair for balconies and verandas.",
        "description": "Nilkamal's moulded armchair shrugs off rain, sun and heavy guests alike. It stacks away when not needed, wipes clean in seconds and is rated for daily outdoor use on balconies, gardens and shopfronts.",
        "specs": {
            "Material": "Moulded plastic",
            "Load": "Up to 100 kg",
            "Weatherproof": "Yes",
            "Stackable": "Yes",
            "Weight": "3.2 kg",
            "Warranty": "1 year",
        },
        "rating": 4.0,
        "num_reviews": 9100,
        "stock": 60,
        "best_for": ["outdoor", "budget buys", "everyday use"],
        "featured": False,
    },
    {
        "id": "PP-079",
        "name": "Signoraware Airtight Container Set (3 pcs)",
        "category": "Home & Lifestyle",
        "price_inr": 399,
        "short_description": "Three airtight, microwave-safe containers for daily storage.",
        "description": "Signoraware's 3-piece set locks moisture out of atta, dal and biscuits with silicone-sealed lids. The containers nest inside each other in the cupboard, and the bodies are microwave and dishwasher safe.",
        "specs": {
            "Pieces": "3 (500 ml, 1 L, 1.5 L)",
            "Material": "Food-grade plastic",
            "Lids": "Silicone gasket, airtight",
            "Microwave safe": "Yes",
            "Dishwasher safe": "Yes",
            "Warranty": "Not applicable",
        },
        "rating": 4.2,
        "num_reviews": 20500,
        "stock": 130,
        "best_for": ["kitchen", "families", "budget buys"],
        "featured": False,
    },
    # ------------------------------ Appliances ------------------------------
    {
        "id": "PP-080",
        "name": "LG 185L Single Door Refrigerator",
        "category": "Appliances",
        "price_inr": 15990,
        "short_description": "5-star 185L direct-cool fridge with a smart inverter compressor.",
        "description": "LG's 185-litre direct-cool fridge suits couples and small families: a 5-star rating that trims electricity bills, a smart inverter compressor backed for ten years, and a toughened glass shelf that shrugs off heavy pots.",
        "specs": {
            "Capacity": "185 L",
            "Energy rating": "5 star",
            "Compressor": "Smart inverter",
            "Defrost": "Direct cool",
            "Warranty": "1 year (10 years compressor)",
        },
        "rating": 4.4,
        "num_reviews": 11700,
        "stock": 20,
        "best_for": ["families", "kitchen", "everyday use"],
        "featured": False,
    },
    {
        "id": "PP-081",
        "name": "Samsung 23L Solo Microwave Oven",
        "category": "Appliances",
        "price_inr": 6790,
        "short_description": "23L solo microwave with rapid defrost and a ceramic enamel cavity.",
        "description": "Samsung's 23-litre solo handles reheating, defrosting and basic cooking with even heat distribution, and the ceramic enamel cavity wipes clean without holding smells. Auto-cook presets cover the usual dal, rice and pizza.",
        "specs": {
            "Capacity": "23 L",
            "Power": "800 W",
            "Cavity": "Ceramic enamel",
            "Presets": "Auto cook, rapid defrost",
            "Display": "LED",
            "Warranty": "1 year",
        },
        "rating": 4.3,
        "num_reviews": 9800,
        "stock": 26,
        "best_for": ["kitchen", "families", "everyday use"],
        "featured": False,
    },
    {
        "id": "PP-082",
        "name": "LG 6.5kg Fully Automatic Top Load Washing Machine",
        "category": "Appliances",
        "price_inr": 16990,
        "short_description": "6.5kg top-loader with a smart inverter motor and 8 wash programmes.",
        "description": "LG's 6.5kg top-loader takes the daily load off a family of three or four: a smart inverter motor backed for ten years, eight wash programmes from gentle woollens to heavy bedding, and smart diagnosis over the phone if anything acts up.",
        "specs": {
            "Capacity": "6.5 kg",
            "Type": "Fully automatic, top load",
            "Motor": "Smart inverter (10 yr warranty)",
            "Programmes": "8",
            "Warranty": "2 years",
        },
        "rating": 4.4,
        "num_reviews": 13900,
        "stock": 16,
        "best_for": ["families", "everyday use"],
        "featured": False,
    },
    {
        "id": "PP-083",
        "name": "Voltas 1.5 Ton 5 Star Split AC",
        "category": "Appliances",
        "price_inr": 36990,
        "short_description": "1.5-ton 5-star inverter split with 100% copper and turbo mode.",
        "description": "Voltas' 1.5-ton inverter split cools a 150 sq ft room quickly through peak Indian summer, with a 100% copper condenser, turbo mode and an anti-dust filter. The 5-star rating keeps running bills manageable.",
        "specs": {
            "Capacity": "1.5 Ton",
            "Energy rating": "5 star",
            "Coil": "100% copper",
            "Specials": "Turbo mode, anti-dust filter",
            "Warranty": "1 year (10 years compressor)",
        },
        "rating": 4.3,
        "num_reviews": 19800,
        "stock": 12,
        "best_for": ["families", "bedrooms", "summer"],
        "featured": False,
    },
    {
        "id": "PP-084",
        "name": "Usha 1200mm High-Speed Ceiling Fan",
        "category": "Appliances",
        "price_inr": 1899,
        "short_description": "1200mm sweep, high-speed ceiling fan with a silent motor.",
        "description": "Usha's 1200mm sweep moves serious air in medium rooms while staying quiet at cruise speed. A high-speed copper-wound motor and a rust-resistant coating make it the workhorse ceiling fan for bedrooms and halls.",
        "specs": {
            "Sweep": "1200 mm",
            "Speed": "High speed",
            "Motor": "Copper wound",
            "Air delivery": "High",
            "Warranty": "2 years",
        },
        "rating": 4.2,
        "num_reviews": 8700,
        "stock": 44,
        "best_for": ["bedrooms", "families", "summer"],
        "featured": False,
    },
    {
        "id": "PP-085",
        "name": "Bajaj Majesty 15L Water Heater",
        "category": "Appliances",
        "price_inr": 6499,
        "short_description": "15L storage geyser with a glass-lined tank, rated to 8 bar.",
        "description": "The Majesty's glass-lined inner tank fights hard-water corrosion — the usual geyser killer — and its 8-bar pressure rating handles high-rise bathrooms. A 2000W element heats a full tank quickly for bucket baths.",
        "specs": {
            "Capacity": "15 L",
            "Power": "2000 W",
            "Tank": "Glass-lined",
            "Pressure rating": "8 bar",
            "Safety": "Thermal cutout, fusible plug",
            "Warranty": "2 years (5 years tank)",
        },
        "rating": 4.3,
        "num_reviews": 12100,
        "stock": 24,
        "best_for": ["winter", "families", "everyday use"],
        "featured": False,
    },
    {
        "id": "PP-086",
        "name": "Philips GC1905 Steam Iron",
        "category": "Appliances",
        "price_inr": 1399,
        "short_description": "1440W steam iron with a non-stick soleplate and steam burst.",
        "description": "The GC1905's non-stick soleplate glides and doesn't grab starched cotton, and 1440W with a steam burst flattens stubborn creases in linen. Self-clean function and a 360° swivel cord finish the job.",
        "specs": {
            "Power": "1440 W",
            "Soleplate": "Non-stick aluminium",
            "Steam": "Burst + spray",
            "Cord": "360° swivel",
            "Tank": "180 ml",
            "Warranty": "2 years",
        },
        "rating": 4.3,
        "num_reviews": 24600,
        "stock": 55,
        "best_for": ["everyday use", "families", "budget buys"],
        "featured": False,
    },
    {
        "id": "PP-087",
        "name": "Eureka Forbes Wet & Dry Vacuum Cleaner",
        "category": "Appliances",
        "price_inr": 5499,
        "short_description": "1400W wet-and-dry vacuum for spills, carpets and car interiors.",
        "description": "This wet-and-dry canister takes on spilt chai, monsoon doormats and car seats alike: 1400W of suction, a blower function for dry leaves and dust, and a washable filter. Wheels and a long cord keep large rooms easy.",
        "specs": {
            "Power": "1400 W",
            "Type": "Wet & dry",
            "Tank": "20 L",
            "Blower": "Yes",
            "Accessories": "Crevice tool, brush, wand",
            "Warranty": "1 year",
        },
        "rating": 4.1,
        "num_reviews": 7400,
        "stock": 22,
        "best_for": ["kitchen", "families", "car care"],
        "featured": False,
    },
    {
        "id": "PP-088",
        "name": "Symphony Diet 3D 30L Air Cooler",
        "category": "Appliances",
        "price_inr": 8499,
        "short_description": "30L tower cooler with three-side honeycomb pads, inverter-ready.",
        "description": "Symphony's Diet 3D throws cool air across a mid-size room on about 175W — roughly two light bulbs — so it sips power compared to an AC and runs on the inverter during cuts. Honeycomb pads on three sides and a handy water-level indicator.",
        "specs": {
            "Capacity": "30 L",
            "Power": "175 W, inverter compatible",
            "Pads": "3-side honeycomb",
            "Air throw": "Long",
            "Warranty": "1 year",
        },
        "rating": 4.2,
        "num_reviews": 10600,
        "stock": 18,
        "best_for": ["summer", "budget buys", "bedrooms"],
        "featured": False,
    },
    {
        "id": "PP-089",
        "name": "Kent Grand 8L RO Water Purifier",
        "category": "Appliances",
        "price_inr": 15499,
        "short_description": "RO + UV purifier with TDS controller and 8L storage.",
        "description": "The Kent Grand combines RO and UV purification with a TDS controller that keeps essential minerals in your water, and stores 8 litres for power cuts. It's built for borewell and tanker water alike.",
        "specs": {
            "Technology": "RO + UV + TDS controller",
            "Storage": "8 L",
            "Purification rate": "~15 L/hr",
            "Mounting": "Wall mount",
            "Filter change alert": "Yes",
            "Warranty": "1 year",
        },
        "rating": 4.3,
        "num_reviews": 16900,
        "stock": 15,
        "best_for": ["families", "kitchen", "health"],
        "featured": False,
    },
    {
        "id": "PP-090",
        "name": "Prestige Sandwich Griller",
        "category": "Appliances",
        "price_inr": 1199,
        "short_description": "700W double-sandwich griller with non-stick plates.",
        "description": "Toasts two stuffed sandwiches at once on non-stick plates that wipe clean in a swipe, and the press handles thick fillings without squashing them flat. A staple for hostel breakfasts and six-o'clock hunger.",
        "specs": {
            "Power": "700 W",
            "Plates": "Non-stick, fixed",
            "Capacity": "2 sandwiches",
            "Indicator": "Ready lights",
            "Warranty": "1 year",
        },
        "rating": 4.1,
        "num_reviews": 18300,
        "stock": 70,
        "best_for": ["kitchen", "students", "budget buys"],
        "featured": False,
    },
    {
        "id": "PP-091",
        "name": "Panasonic 1.8L Automatic Rice Cooker",
        "category": "Appliances",
        "price_inr": 3199,
        "short_description": "1.8L rice cooker with keep-warm mode and a steaming basket.",
        "description": "Panasonic's 1.8-litre cooker makes rice for four to six people and switches to keep-warm on its own; the steamer basket handles veggies and momos while the rice cooks below. Non-stick inner pot and measuring cup included.",
        "specs": {
            "Capacity": "1.8 L (serves 4-6)",
            "Power": "640 W",
            "Functions": "Cook + keep warm",
            "Accessories": "Steamer basket, measuring cup",
            "Inner pot": "Non-stick",
            "Warranty": "1 year",
        },
        "rating": 4.3,
        "num_reviews": 8900,
        "stock": 30,
        "best_for": ["kitchen", "families", "students"],
        "featured": False,
    },
    # ------------------------- Beauty & Personal Care -----------------------
    {
        "id": "PP-092",
        "name": "Philips BT3223 Beard Trimmer",
        "category": "Beauty & Personal Care",
        "price_inr": 1699,
        "short_description": "Cordless DuraPower trimmer with 90-minute runtime and 1mm precision.",
        "description": "Philips' BT3223 runs 90 minutes on a full charge and holds its battery health for years thanks to DuraPower. Self-sharpening blades, settings from 0.5 to 10mm and a fully washable head.",
        "specs": {
            "Runtime": "Up to 90 minutes",
            "Charging": "Full charge in ~8 hours",
            "Blades": "Self-sharpening stainless",
            "Settings": "0.5 - 10 mm",
            "Washable": "Yes",
            "Warranty": "2 years",
        },
        "rating": 4.4,
        "num_reviews": 31500,
        "stock": 60,
        "best_for": ["everyday use", "grooming", "travel"],
        "featured": False,
    },
    {
        "id": "PP-093",
        "name": "Philips HP8100 Hair Dryer",
        "category": "Beauty & Personal Care",
        "price_inr": 1195,
        "short_description": "1600W foldable dryer with three heat settings and a cool shot.",
        "description": "The HP8100 folds into travel bags and dries thick hair fast at 1600W, with three heat settings and a cool shot to set the style. The narrow concentrator directs air exactly where you want it.",
        "specs": {
            "Power": "1600 W",
            "Settings": "3 heat, 2 speed",
            "Attachment": "Concentrator nozzle",
            "Foldable": "Yes",
            "Cord": "1.5 m",
            "Warranty": "2 years",
        },
        "rating": 4.3,
        "num_reviews": 27300,
        "stock": 65,
        "best_for": ["everyday use", "travel", "grooming"],
        "featured": False,
    },
    {
        "id": "PP-094",
        "name": "Oral-B Vitality Electric Toothbrush",
        "category": "Beauty & Personal Care",
        "price_inr": 2199,
        "short_description": "Round oscillating head with a built-in two-minute timer.",
        "description": "The Vitality's small round head oscillates to break up plaque better than manual scrubbing, and the built-in timer nudges you to a full two minutes of brushing. A charge lasts several days, and refill heads are everywhere.",
        "specs": {
            "Technology": "Oscillating round head",
            "Timer": "Built-in 2-minute",
            "Mode": "Daily clean",
            "Battery": "Multi-day per charge",
            "Refills": "Oral-B refill heads",
            "Warranty": "1 year",
        },
        "rating": 4.4,
        "num_reviews": 14700,
        "stock": 35,
        "best_for": ["everyday use", "grooming", "families"],
        "featured": False,
    },
    {
        "id": "PP-095",
        "name": "Mamaearth Vitamin C Face Serum",
        "category": "Beauty & Personal Care",
        "price_inr": 399,
        "short_description": "Vitamin C with turmeric for brighter, evener skin tone.",
        "description": "A lightweight daily serum pairing vitamin C with turmeric to fade dullness and even out tone. It absorbs in seconds with no stickiness and sits comfortably under sunscreen.",
        "specs": {
            "Size": "30 ml",
            "Key actives": "Vitamin C, turmeric",
            "Skin type": "All",
            "Use": "AM routine, under sunscreen",
            "Certification": "Made Safe certified, toxin-free",
            "Warranty": "Not applicable",
        },
        "rating": 4.2,
        "num_reviews": 41800,
        "stock": 90,
        "best_for": ["everyday use", "gifting", "self care"],
        "featured": False,
    },
    {
        "id": "PP-096",
        "name": "Nivea Deep Moisture Body Lotion (600ml)",
        "category": "Beauty & Personal Care",
        "price_inr": 449,
        "short_description": "48-hour deep-moisture lotion for dry to very dry skin.",
        "description": "Nivea's Deep Moisture lotion sinks in without a greasy film and keeps dry winter skin comfortable for up to 48 hours. Dermatologically tested, lightly fragranced, and one bottle lasts a family for weeks.",
        "specs": {
            "Size": "600 ml",
            "Skin type": "Dry to very dry",
            "Hydration": "Up to 48 hours",
            "Fragrance": "Light, fresh",
            "Dermatologically tested": "Yes",
            "Warranty": "Not applicable",
        },
        "rating": 4.5,
        "num_reviews": 33900,
        "stock": 110,
        "best_for": ["winter", "families", "everyday use"],
        "featured": False,
    },
    # ---------------------------- Sports & Fitness --------------------------
    {
        "id": "PP-097",
        "name": "Cosco Torpedo Football (Size 5)",
        "category": "Sports & Fitness",
        "price_inr": 649,
        "short_description": "Size-5 moulded rubber football built for rough ground.",
        "description": "The Torpedo's moulded rubber cover survives tarmac and street matches that destroy stitched balls. The butyl bladder holds air for weeks, and size 5 suits ages twelve and up.",
        "specs": {
            "Size": "5",
            "Cover": "Moulded rubber",
            "Bladder": "Butyl",
            "Surface": "Rough / street",
            "Age": "12+",
            "Warranty": "Not applicable",
        },
        "rating": 4.1,
        "num_reviews": 8800,
        "stock": 80,
        "best_for": ["outdoor", "kids", "fitness"],
        "featured": False,
    },
    {
        "id": "PP-098",
        "name": "Kore Yoga Mat (6mm)",
        "category": "Sports & Fitness",
        "price_inr": 549,
        "short_description": "6mm anti-skid mat that cushions knees and spines.",
        "description": "Kore's 6mm mat cushions knees and spines on hard floors while the textured surface grips poses instead of sliding. It rolls up tight with the included carry strap for the gym bag.",
        "specs": {
            "Thickness": "6 mm",
            "Material": "NBR foam",
            "Size": "173 x 61 cm",
            "Grip": "Textured anti-skid",
            "Includes": "Carry strap",
            "Warranty": "Not applicable",
        },
        "rating": 4.2,
        "num_reviews": 25400,
        "stock": 95,
        "best_for": ["fitness", "gym", "home workouts"],
        "featured": False,
    },
    {
        "id": "PP-099",
        "name": "SG Kashmir Willow Cricket Bat",
        "category": "Sports & Fitness",
        "price_inr": 1499,
        "short_description": "Kashmir willow bat, short handle, for practice and gully cricket.",
        "description": "SG's Kashmir willow offers real thump without the English-willow price: a short-handle shape suited to teenagers and adults, traditionally profiled for drives. It needs light knocking in before hard balls.",
        "specs": {
            "Willow": "Kashmir",
            "Handle": "Short",
            "Weight": "1.1 - 1.2 kg",
            "Profile": "Traditional",
            "Warranty": "Not applicable",
        },
        "rating": 4.2,
        "num_reviews": 6100,
        "stock": 30,
        "best_for": ["outdoor", "gifting", "kids"],
        "featured": False,
    },
    {
        "id": "PP-100",
        "name": "Kore PVC Dumbbell Set (2 x 5 kg)",
        "category": "Sports & Fitness",
        "price_inr": 849,
        "short_description": "Pair of 5kg PVC-coated dumbbells with contoured grips.",
        "description": "A 2 x 5 kg PVC pair that won't scratch floors or rust in humid rooms — the starter kit for curls, presses and rows at home. Contoured grips keep twenty-rep sets comfortable.",
        "specs": {
            "Weight": "2 x 5 kg",
            "Coating": "PVC",
            "Grip": "Contoured",
            "Use": "Home strength training",
            "Warranty": "Not applicable",
        },
        "rating": 4.1,
        "num_reviews": 15200,
        "stock": 60,
        "best_for": ["fitness", "home workouts", "beginners"],
        "featured": False,
    },
]

PRODUCT_INDEX: Dict[str, Dict[str, Any]] = {p["id"]: p for p in PRODUCTS}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def format_inr(amount: float) -> str:
    """Format a rupee amount using the Indian numbering system, e.g. 1,25,000."""
    whole = int(round(amount))
    s = str(abs(whole))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return f"-{s}" if whole < 0 else s


def price_display(product: Dict[str, Any]) -> str:
    return f"{CURRENCY_SYMBOL}{format_inr(product['price_inr'])}"


def product_summary(product: Dict[str, Any]) -> Dict[str, Any]:
    """Compact, JSON-safe view of a product (used by AI tools and API)."""
    return {
        "id": product["id"],
        "name": product["name"],
        "category": product["category"],
        "price_inr": product["price_inr"],
        "price_display": price_display(product),
        "currency": CURRENCY,
        "short_description": product["short_description"],
        "rating": product["rating"],
        "num_reviews": product["num_reviews"],
        "stock": product["stock"],
        "best_for": product["best_for"],
        "key_specs": dict(list(product["specs"].items())[:4]),
        "image": f"/assets/products/{product['id']}.jpg",
    }


def product_full(product: Dict[str, Any]) -> Dict[str, Any]:
    """Complete public view of a product for the API."""
    out = product_summary(product)
    out.update(
        {
            "description": product["description"],
            "specs": product["specs"],
            "featured": product["featured"],
        }
    )
    return out


def get_product(product_id: str) -> Optional[Dict[str, Any]]:
    return PRODUCT_INDEX.get(product_id)


# ---------------------------------------------------------------------------
# Search logic (tool: search_catalogue)
# ---------------------------------------------------------------------------

_STOPWORDS = {
    "a", "an", "the", "for", "with", "and", "or", "to", "of", "in", "on",
    "under", "below", "above", "over", "best", "good", "want", "need",
    "looking", "show", "find", "me", "my", "i", "is", "are", "any", "some",
    "please", "can", "you", "recommend", "suggestions", "budget", "within",
    "do", "does", "have", "has", "had", "it", "we", "your",
}


_BUDGET_RE = re.compile(
    r"(?:under|below|less than|max|upto|up to|within|budget(?:\s+of)?|around|about)"
    r"\s*(?:\u20b9|rs\.?|inr)?\s*(\d+(?:\.\d+)?)\s*(k|kk|lac|lakh|lakhs|crore)?\b",
    re.IGNORECASE,
)
_CURRENCY_RE = re.compile(
    r"(?:\u20b9|rs\.?|inr)\s*(\d+(?:\.\d+)?)\s*(k|kk|lac|lakh|lakhs|crore)?\b", re.IGNORECASE
)
_SUFFIX_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(k|kk|lac|lakh|lakhs|crore)\b", re.IGNORECASE)


def _extract_budget(text: str) -> Optional[float]:
    """Extract a maximum INR budget from text like 'under 60k', '₹25,000', '1.5 lakh'.

    Only numbers with explicit budget context count (budget keywords, a ₹/rs/INR
    marker, or a k/lakh/crore suffix) — so 'PlayStation 6' or 'WH-1000XM5' are
    NOT misread as budgets.
    """
    if not text:
        return None
    t = text.replace(",", " ")
    m = _BUDGET_RE.search(t) or _CURRENCY_RE.search(t) or _SUFFIX_RE.search(t)
    if not m:
        return None
    value = float(m.group(1))
    unit = (m.group(2) or "").lower()
    if unit in ("k", "kk"):
        value *= 1000
    elif unit in ("lac", "lakh", "lakhs"):
        value *= 100000
    elif unit == "crore":
        value *= 10000000
    elif value < 100:
        # "under 60" in an INR context almost always means ₹60,000
        value *= 1000
    return value


def _tokenize(text: str) -> List[str]:
    # Pure-digit tokens are skipped: numbers in queries are budgets, and their
    # fragments ("000" from ₹60,000) would otherwise substring-match unrelated
    # product names like "WH-1000XM5" or "20000mAh". Budgets are handled by
    # _extract_budget() instead.
    return [
        w
        for w in re.split(r"[^a-z0-9]+", (text or "").lower())
        if w and w not in _STOPWORDS and len(w) > 1 and not w.isdigit()
    ]


def _fuzzy_in(haystack: str, needle: str) -> bool:
    """Match a search term against haystack text.

    Whole words only: the needle must appear as a complete word (or fuzzy-match
    one) — a bare substring like 'do' must not match inside 'airdopes', and
    '000' must not match inside 'WH-1000XM5'. Hyphenated haystack words are
    split so 'wh' / 'xm5' match 'WH-1000XM5'.
    """
    if not needle:
        return False
    if f" {needle} " in f" {haystack} ":
        return True
    for word in re.split(r"[^a-z0-9]+", haystack):
        if not word:
            continue
        if word == needle:
            return True
        if len(needle) >= 4 and SequenceMatcher(None, word, needle).ratio() >= 0.82:
            return True
    return False


def search_catalogue(
    query: Optional[str] = None,
    category: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    keywords: Optional[str] = None,
    limit: int = 6,
) -> Dict[str, Any]:
    """Search the trusted catalogue. Mirrors the AI tool of the same name."""
    limit = max(1, min(int(limit or 6), 12))
    budget = _extract_budget(query or "") or (max_price if max_price is not None else None)

    cat = (category or "").strip()
    if cat:
        # tolerate partial category names like "laptop" -> "Laptops"
        best_cat, best_score = None, 0.0
        for c in CATEGORIES:
            score = SequenceMatcher(None, cat.lower(), c.lower()).ratio()
            if score > best_score:
                best_cat, best_score = c, score
        if best_score >= 0.55:
            cat = best_cat
        else:
            cat = category

    terms = _tokenize(query or "") + _tokenize(keywords or "")

    scored: List[tuple] = []
    for p in PRODUCTS:
        # --- filters ---
        if cat and p["category"].lower() != cat.lower():
            continue
        if min_price is not None and p["price_inr"] < float(min_price):
            continue
        if budget is not None and p["price_inr"] > float(budget):
            continue
        # --- scoring ---
        hay_name = p["name"].lower()
        hay_cat = p["category"].lower()
        hay_tags = " ".join(p["best_for"]).lower()
        hay_desc = (p["short_description"] + " " + p["description"]).lower()
        hay_specs = " ".join(f"{k} {v}" for k, v in p["specs"].items()).lower()
        score = 0.0
        matched_terms = 0
        for term in terms:
            if _fuzzy_in(hay_name, term):
                score += 6.0
                matched_terms += 1
            elif _fuzzy_in(hay_cat, term):
                score += 4.0
                matched_terms += 1
            elif _fuzzy_in(hay_tags, term):
                score += 3.5
                matched_terms += 1
            elif _fuzzy_in(hay_desc, term):
                score += 2.0
                matched_terms += 1
            elif _fuzzy_in(hay_specs, term):
                score += 1.5
                matched_terms += 1
        if terms and matched_terms == 0:
            continue  # query terms exist but nothing matched
        if not terms and cat is None and budget is None and min_price is None:
            score = 1.0  # bare browse: return catalogue order
        # light tie-breakers: rating and popularity
        score += p["rating"] * 0.1 + min(p["num_reviews"], 50000) / 50000 * 0.5
        scored.append((score, p))

    scored.sort(key=lambda sp: (-sp[0], sp[1]["price_inr"]))
    results = [product_summary(p) for _, p in scored[:limit]]
    return {
        "currency": CURRENCY,
        "count": len(results),
        "products": results,
        "note": (
            f"Returned {len(results)} real products from the PayPilot catalogue "
            f"(prices in INR). Recommend only these products."
        ),
    }


# ---------------------------------------------------------------------------
# Compare logic (tool: compare_products)
# ---------------------------------------------------------------------------

_SPEC_WIN_KEYS = ["RAM", "RAM / Storage", "Battery", "Storage", "Capacity", "Power"]


def _resolve_product(ref: str) -> Optional[Dict[str, Any]]:
    ref = (ref or "").strip()
    if not ref:
        return None
    if ref.upper() in PRODUCT_INDEX:
        return PRODUCT_INDEX[ref.upper()]
    # try to complete a bare id like "PP-1"
    m = re.fullmatch(r"PP-?(\d+)", ref, re.IGNORECASE)
    if m:
        pid = f"PP-{int(m.group(1)):03d}"
        if pid in PRODUCT_INDEX:
            return PRODUCT_INDEX[pid]
    best, best_score = None, 0.0
    for p in PRODUCTS:
        for cand in (p["name"], p["name"].lower(), " ".join(p["best_for"])):
            score = SequenceMatcher(None, ref.lower(), cand.lower()).ratio()
            if score > best_score:
                best, best_score = p, score
    return best if best_score >= 0.45 else None


def _numeric_from_spec(value: Any) -> Optional[float]:
    m = re.search(r"(\d+(?:\.\d+)?)", str(value))
    return float(m.group(1)) if m else None


def compare_products(product_refs: List[str], budget: Optional[float] = None) -> Dict[str, Any]:
    """Compare 2-3 catalogue products using real data only."""
    resolved: List[Dict[str, Any]] = []
    unresolved: List[str] = []
    seen = set()
    for ref in product_refs:
        p = _resolve_product(ref)
        if p is None:
            unresolved.append(ref)
        elif p["id"] not in seen:
            seen.add(p["id"])
            resolved.append(p)

    if len(resolved) < 2:
        return {
            "error": (
                "Could not identify at least two catalogue products to compare."
                + (f" Unrecognised: {', '.join(unresolved)}." if unresolved else "")
                + " Ask the user to name products from the catalogue, or search first."
            )
        }

    prices = [p["price_inr"] for p in resolved]
    ratings = [p["rating"] for p in resolved]
    cheapest = resolved[prices.index(min(prices))]
    best_rated = resolved[ratings.index(max(ratings))]

    entries = []
    for p in resolved:
        pros, cons = [], []
        if p is cheapest and len(resolved) > 1:
            pros.append(f"Lowest price in this comparison ({price_display(p)})")
        else:
            cons.append(f"Costs {format_inr(p['price_inr'] - min(prices))} more than the cheapest option")
        if p is best_rated and p["rating"] >= 4.0:
            pros.append(f"Highest customer rating ({p['rating']}/5 from {p['num_reviews']:,} reviews)")
        if budget is not None:
            if p["price_inr"] <= budget:
                pros.append(f"Fits the \u20b9{format_inr(budget)} budget")
            else:
                cons.append(f"Over the \u20b9{format_inr(budget)} budget by {price_display({'price_inr': p['price_inr'] - budget})}")
        # spec-based wins against the compared set
        for key in p["specs"]:
            if key not in _SPEC_WIN_KEYS:
                continue
            vals = []
            for q in resolved:
                v = _numeric_from_spec(q["specs"].get(key, ""))
                if v is not None:
                    vals.append((v, q["id"]))
            if len(vals) >= 2 and vals and max(vals)[1] == p["id"] and len({v for v, _ in vals}) > 1:
                pros.append(f"Best {key} in this comparison ({p['specs'][key]})")
        if p["stock"] <= 15:
            cons.append("Low stock — only a few units left")
        if not cons:
            cons.append("See detailed specs for trade-offs")
        entries.append(
            {
                "id": p["id"],
                "name": p["name"],
                "category": p["category"],
                "price_inr": p["price_inr"],
                "price_display": price_display(p),
                "rating": p["rating"],
                "stock": p["stock"],
                "specs": p["specs"],
                "advantages": pros,
                "disadvantages": cons,
                "best_for": p["best_for"],
            }
        )

    rec = cheapest if cheapest is best_rated else (
        best_rated if best_rated["price_inr"] <= (budget if budget is not None else float("inf")) else cheapest
    )
    return {
        "currency": CURRENCY,
        "count": len(entries),
        "products": entries,
        "recommendation": (
            f"{rec['name']} is the strongest pick overall: {price_display(rec)}, "
            f"rated {rec['rating']}/5, best for {', '.join(rec['best_for'])}."
        ),
        "note": "Comparison generated from real catalogue data (prices in INR).",
    }


# ---------------------------------------------------------------------------
# Details logic (tool: get_product_details)
# ---------------------------------------------------------------------------

def get_product_details(product_ref: str) -> Dict[str, Any]:
    p = _resolve_product(product_ref)
    if p is None:
        return {
            "error": (
                f"No product matching '{product_ref}' exists in the PayPilot catalogue. "
                "Do not invent details — tell the user it is not available and "
                "offer to search for alternatives."
            )
        }
    return {
        "product": product_full(p),
        "note": "Real catalogue record. Use only this data when describing the product.",
    }

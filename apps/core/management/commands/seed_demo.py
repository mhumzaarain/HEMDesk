import os
import random
import sys
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import Roles
from apps.equipment.models import (
    Accessory,
    AccessoryEvent,
    AccessoryStatus,
    AccessoryType,
    Department,
    Equipment,
    EquipmentStatus,
    StatusEvent,
)
from apps.equipment.services import (
    adjust_stock,
    attach_accessory,
    condemn_equipment,
    create_accessory_type,
    repair_accessory,
    replace_accessory,
    update_accessory,
)
from apps.maintenance.models import (
    Complaint,
    FaultCategory,
    PPMInterval,
    PPMOutcome,
    PPMRecord,
    PPMSchedule,
    WorkOrder,
    WorkOrderStatus,
)
from apps.maintenance.services import (
    add_remark,
    complete_ppm,
    complete_work_order,
    lodge_complaint,
    open_work_order,
    set_ppm_schedule,
    start_repair,
)

DEVICES = [
    ("MRI Scanner", "Siemens", "Magnetom Aera", True),
    ("CT Scanner", "GE Healthcare", "Revolution ACT", True),
    ("Angiography System", "Philips", "Azurion 7", True),
    ("Ventilator", "Hamilton", "C2", True),
    ("Infusion Pump", "B.Braun", "Perfusor Space", False),
    ("Patient Monitor", "Mindray", "uMEC 12", False),
    ("Defibrillator", "Zoll", "R Series", False),
    ("ECG Machine", "Schiller", "Cardiovit AT-102", False),
    ("Suction Machine", "Yuwell", "7A-23D", False),
    ("Syringe Pump", "Medtronic", "SP-500", False),
    ("Ultrasound", "Mindray", "DC-70", False),
    ("Anesthesia Machine", "Draeger", "Fabius Plus", False),
]
COMPLAINT_TEXTS = [
    "Screen goes black after a few minutes of use.",
    "Machine will not power on at all.",
    "Loud clicking noise during operation.",
    "Battery drains within minutes when unplugged.",
    "Error code E-42 shown, alarm keeps beeping.",
    "Readings look wrong compared to the backup unit.",
    "Smells like something is burning inside.",
    "Touch panel not responding to input.",
]
DELAY_TEXTS = [
    "Waiting for spare part from vendor.",
    "Part shipment delayed due to holidays.",
    "Awaiting quotation approval from procurement.",
]
ACCESSORY_TYPES = [
    ("ECG cable", "Patient Monitor Mindray uMEC 12", 4),
    ("SpO2 probe", "Patient Monitor Mindray uMEC 12", 3),
    ("IBP probe", "Patient Monitor Mindray uMEC 12", 2),
    ("NIBP cuff", "Patient Monitor Mindray uMEC 12", 5),
    ("Ventilator circuit", "Ventilator Hamilton C2", 5),
    ("ECG cable", "Defibrillator Zoll R Series", 2),
]


def backdate(model, pk, **fields):
    model.objects.filter(pk=pk).update(**fields)


class Command(BaseCommand):
    help = "Seed the database with realistic demo data. Refuses on non-empty DB."

    def handle(self, *args, **options):
        if Equipment.objects.exists():
            self.stderr.write("Database already has equipment; refusing to seed.")
            sys.exit(1)
        random.seed(42)
        User = get_user_model()
        now = timezone.now()
        # Shared login password for all seeded demo accounts. Configurable via
        # the DEMO_PASSWORD env var (set in .env); defaults to "demo1234".
        demo_password = os.environ.get("DEMO_PASSWORD", "demo1234")

        departments = [
            Department.objects.create(name=n, location=loc)
            for n, loc in [
                ("ICU", "Block A, Floor 2"),
                ("Radiology", "Block B, Ground"),
                ("Emergency", "Block A, Ground"),
                ("Cardiology", "Block C, Floor 1"),
                ("Operation Theater", "Block A, Floor 3"),
            ]
        ]
        admin = User.objects.create_user(
            username="admin",
            password=demo_password,
            employee_id="EMP-900",
            role=Roles.ADMIN,
            first_name="Ayesha",
            last_name="Malik",
            is_staff=True,
            is_superuser=True,
        )
        engineers = [
            User.objects.create_user(
                username=f"engineer{i}",
                password=demo_password,
                employee_id=f"EMP-10{i}",
                role=Roles.ENGINEER,
                first_name=f"Engineer{i}",
                last_name="Demo",
            )
            for i in range(1, 4)
        ]
        staff = [
            User.objects.create_user(
                username=f"staff{i}",
                password=demo_password,
                employee_id=f"EMP-00{i}",
                role=Roles.STAFF,
                first_name=f"Staff{i}",
                last_name="Demo",
                department=random.choice(departments),
            )
            for i in range(1, 11)
        ]

        devices = []
        serial = 1000
        for name, maker, model, critical in DEVICES:
            for _ in range(random.randint(3, 7)):
                serial += 1
                devices.append(
                    Equipment.objects.create(
                        name=name,
                        manufacturer=maker,
                        vendor="MedServe Ltd",
                        model_number=model,
                        serial_number=f"SN-{serial}",
                        department=random.choice(departments),
                        is_critical_asset=critical,
                        purchase_date=now.date()
                        - timedelta(days=random.randint(400, 3000)),
                        installation_date=now.date()
                        - timedelta(days=random.randint(100, 400)),
                    )
                )

        # accessory catalog, backup stock and fitted units. Deterministic on
        # purpose: consuming `random` here would shift the seeded history.
        type_by_key = {}
        for type_name, equipment_name, qty in ACCESSORY_TYPES:
            accessory_type = create_accessory_type(
                admin, name=type_name, equipment_name=equipment_name
            )
            adjust_stock(accessory_type, admin, qty, "Initial store stock")
            type_by_key[(type_name, equipment_name)] = accessory_type

        faulty_seeded = False
        for device in devices:
            for type_name, equipment_name, _qty in ACCESSORY_TYPES:
                if not equipment_name.startswith(device.name):
                    continue
                accessory = attach_accessory(
                    device,
                    admin,
                    type_by_key[(type_name, equipment_name)],
                    from_stock=False,
                )
                if not faulty_seeded and type_name == "SpO2 probe":
                    update_accessory(
                        accessory,
                        admin,
                        status=AccessoryStatus.FAULTY,
                        notes="Intermittent readings; replacement requested.",
                    )
                    faulty_seeded = True

        # ~90 days of complaint -> repair history through the real services
        for day_offset in range(90, 0, -2):
            working_devices = [d for d in devices if d.status == "working"]
            if not working_devices:
                continue
            device = random.choice(working_devices)
            device.refresh_from_db()
            if device.status != "working":
                continue
            reporter = random.choice(staff)
            engineer = random.choice(engineers)
            t0 = now - timedelta(days=day_offset, hours=random.randint(0, 8))
            complaint = lodge_complaint(
                reporter, device, random.choice(COMPLAINT_TEXTS)
            )
            backdate(Complaint, complaint.pk, created_at=t0)
            wo = open_work_order(device, engineer)
            backdate(WorkOrder, wo.pk, opened_at=t0 + timedelta(hours=1))
            wo.refresh_from_db()
            wo = start_repair(wo, engineer)
            started = t0 + timedelta(hours=random.randint(2, 24))
            backdate(WorkOrder, wo.pk, repair_started_at=started)
            repair_hours = random.choice([2, 4, 6, 12, 24, 48, 96])
            if repair_hours >= 48:
                add_remark(wo, engineer, random.choice(DELAY_TEXTS), kind="delay")
            wo.refresh_from_db()
            wo = complete_work_order(
                wo,
                engineer,
                fault_category=random.choice(list(FaultCategory.objects.all())),
                remark="Repaired and tested OK.",
            )
            done = started + timedelta(hours=repair_hours)
            backdate(WorkOrder, wo.pk, repair_completed_at=done, closed_at=done)
            # backdate the two status events of this cycle
            for event in StatusEvent.objects.filter(work_order=wo):
                ts = started if event.new_status == "in_repair" else done
                backdate(StatusEvent, event.pk, created_at=ts)

        # a couple of currently-open complaints for the queue demo
        for _ in range(4):
            working_devices = [d for d in devices if d.status == "working"]
            if not working_devices:
                continue
            device = random.choice(working_devices)
            device.refresh_from_db()
            if device.status == "working":
                lodge_complaint(
                    random.choice(staff), device, random.choice(COMPLAINT_TEXTS)
                )

        # two condemned devices
        condemn_pool = [d for d in devices if not d.is_critical_asset]
        for device in random.sample(condemn_pool, min(2, len(condemn_pool))):
            device.refresh_from_db()
            if device.status == "working":
                condemn_equipment(
                    device,
                    admin,
                    remark="Beyond economical repair.",
                    condemned_location="Condemned store, basement",
                )

        # PPM schedules for ~15 devices; past completions give a natural
        # mix of overdue / due-soon / on-track next_due dates.
        ppm_pool = [d for d in devices if d.status == "working"]
        for device in random.sample(ppm_pool, min(15, len(ppm_pool))):
            device.refresh_from_db()
            if device.status != "working":
                continue
            engineer = random.choice(engineers)
            interval = random.choice(
                [PPMInterval.MONTHLY, PPMInterval.QUARTERLY, PPMInterval.BIANNUAL]
            )
            schedule = set_ppm_schedule(
                device,
                engineer,
                interval,
                now.date() + timedelta(days=random.randint(-30, 45)),
            )
            if random.random() < 0.6:
                performed = now.date() - timedelta(days=random.randint(20, 100))
                complete_ppm(
                    schedule,
                    engineer,
                    random.choice(
                        [
                            PPMOutcome.PASSED,
                            PPMOutcome.PASSED,
                            PPMOutcome.PASSED_WITH_REMARKS,
                        ]
                    ),
                    performed,
                    remarks="Routine PPM completed.",
                )

        # accessory replacement / repair history on completed work orders.
        # Placed last on purpose: random draws here cannot shift the earlier
        # seeded world. Services require an ACTIVE work order, so each chosen
        # completed WO is flipped to in_progress, the event is recorded
        # through the real service, and the WO is flipped back (one at a
        # time — no other active WOs exist here, so the one-active-WO
        # constraint cannot trip). Only WORKING accessories are picked, so
        # the single pre-seeded faulty SpO2 probe stays the only faulty one.
        completed_pool = list(
            WorkOrder.objects.filter(
                status=WorkOrderStatus.COMPLETED,
                equipment__accessories__isnull=False,
            )
            .exclude(equipment__status=EquipmentStatus.CONDEMNED)
            .distinct()
            .order_by("opened_at")
        )
        replaced = repaired = 0
        for wo in completed_pool:
            if replaced >= 6 and repaired >= 3:
                break
            accessory = (
                wo.equipment.accessories.filter(status=AccessoryStatus.WORKING)
                .select_related("type")
                .order_by("id")
                .first()
            )
            if accessory is None:
                continue
            engineer = random.choice(engineers)
            WorkOrder.objects.filter(pk=wo.pk).update(
                status=WorkOrderStatus.IN_PROGRESS
            )
            wo.refresh_from_db()
            event = None
            if replaced < 6 and accessory.type.stock_qty > 0:
                event = replace_accessory(
                    accessory,
                    engineer,
                    wo,
                    remark="Worn out; replaced from backup stock.",
                )
                replaced += 1
                backdate(
                    Accessory, accessory.pk, condemned_at=wo.repair_completed_at
                )
            elif repaired < 3:
                update_accessory(
                    accessory, engineer, status=AccessoryStatus.FAULTY
                )
                event = repair_accessory(
                    accessory, engineer, wo, remark="Connector re-soldered."
                )
                repaired += 1
            WorkOrder.objects.filter(pk=wo.pk).update(
                status=WorkOrderStatus.COMPLETED
            )
            if event is not None:
                backdate(
                    AccessoryEvent, event.pk, created_at=wo.repair_completed_at
                )

        # make the restock strip visible out of the box: one type at zero
        low_type = (
            AccessoryType.objects.filter(stock_qty__gt=0).order_by("id").first()
        )
        if low_type is not None:
            adjust_stock(
                low_type, admin, -low_type.stock_qty, "Issued to wards as spares"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {Equipment.objects.count()} devices, "
                f"{AccessoryType.objects.count()} accessory types, "
                f"{Accessory.objects.count()} accessories, "
                f"{AccessoryEvent.objects.count()} accessory events, "
                f"{Complaint.objects.count()} complaints, "
                f"{WorkOrder.objects.count()} work orders, "
                f"{PPMSchedule.objects.count()} PPM schedules, "
                f"{PPMRecord.objects.count()} PPM records. "
                f"Logins: admin, engineer1, staff1 — password: {demo_password}"
            )
        )

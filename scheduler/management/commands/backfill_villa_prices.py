import re
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand

from scheduler.models import Proposal


EURO_PRICE = re.compile(
    r"(?:€|\bEUR\b)\s*(?P<prefix>\d[\d.,\s]*)|(?P<suffix>\d[\d.,\s]*)\s*(?:€|\bEUR\b)",
    re.IGNORECASE,
)


def parse_euro_price(value):
    """Parse a single price token, accepting common EU and US grouping formats."""
    match = EURO_PRICE.search(value)
    if not match:
        return None
    number = (match.group("prefix") or match.group("suffix")).strip().replace(" ", "")
    if number.count(",") and number.count("."):
        decimal_separator = "," if number.rfind(",") > number.rfind(".") else "."
        grouping_separator = "." if decimal_separator == "," else ","
        number = number.replace(grouping_separator, "").replace(decimal_separator, ".")
    elif "," in number or "." in number:
        separator = "," if "," in number else "."
        whole, fraction = number.rsplit(separator, 1)
        number = whole.replace(separator, "") if len(fraction) == 3 else f"{whole}.{fraction}"
    try:
        amount = Decimal(number)
    except InvalidOperation:
        return None
    return amount if amount >= 0 else None


class Command(BaseCommand):
    help = "Backfill unambiguous EUR prices from legacy villa price notes. Runs as a preview unless --apply is provided."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write the extracted values to the database.")

    def handle(self, *args, **options):
        candidates = []
        for proposal in Proposal.objects.filter(type=Proposal.Type.STAY, total_price__isnull=True).exclude(price=""):
            amount = parse_euro_price(proposal.price)
            if amount is not None:
                candidates.append((proposal, amount))

        for proposal, amount in candidates:
            action = "Would update" if not options["apply"] else "Updated"
            self.stdout.write(f"{action} #{proposal.pk} {proposal.title!r}: {amount} EUR")
            if options["apply"]:
                proposal.total_price = amount
                proposal.currency = "EUR"
                proposal.save(update_fields=["total_price", "currency", "updated_at"])

        suffix = " Run again with --apply to save changes." if not options["apply"] else ""
        self.stdout.write(self.style.SUCCESS(f"{len(candidates)} legacy villa price(s) matched.{suffix}"))

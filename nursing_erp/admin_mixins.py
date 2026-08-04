"""Building-scoped admin mixin for role-based data access.

Usage:
    @admin.register(Resident)
    class ResidentAdmin(BuildingScopeMixin, ModelAdmin):
        building_field = "building"   # direct field on this model
        ...

    @admin.register(NursingLog)
    class NursingLogAdmin(BuildingScopeMixin, ModelAdmin):
        building_field = "resident__building"  # FK chain to building
        ...
"""


class BuildingScopeMixin:
    """Filter queryset by the logged-in user's assigned building.

    - Superusers see everything.
    - Users with an Employee profile see only records matching their
      assigned building (or their staff member's building for staff models).
    - Users without an Employee profile (e.g. pure Django admin accounts
      not yet linked) see everything (fail-open for admin setup).
    """

    building_field: str | None = None  # e.g. "building" or "resident__building"

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        if not self.building_field:
            return qs
        try:
            employee = request.user.employee
        except Exception:
            return qs  # No Employee linked → full access (admin setup phase)
        if not employee.building:
            return qs  # No building assigned → full access (dept heads)
        return qs.filter(**{self.building_field: employee.building})

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Also scope FK lookups (e.g. when picking a resident, show only
        those in the same building)."""
        from residents.models import Resident

        field = super().formfield_for_foreignkey(db_field, request, **kwargs)
        if field is None:
            return field
        if request.user.is_superuser:
            return field
        try:
            employee = request.user.employee
        except Exception:
            return field
        if not employee.building:
            return field

        # Scope Resident lookups to the caregiver's building
        if db_field.remote_field and db_field.remote_field.model is Resident:
            field.queryset = field.queryset.filter(building=employee.building)

        return field

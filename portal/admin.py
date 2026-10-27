from django.contrib import admin

from .models import (
    Attendance, Department, Designation, Employee, Holiday, LeaveRequest, LeaveType, Notification, Project,
    ProjectAssignment, ProjectUpdate, Team,
)

admin.site.register(Department)
admin.site.register(Team)
admin.site.register(Designation)
admin.site.register(LeaveType)


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ("employee_id", "user", "designation", "department", "role", "status")
    search_fields = ("employee_id", "user__username", "user__first_name", "user__last_name")


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ("employee", "date", "in_time", "out_time", "work_mode")
    list_filter = ("work_mode", "date")


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "status", "completion", "start_date", "end_date")
    filter_horizontal = ("employees",)


@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ("employee", "leave_type", "start_date", "end_date", "days", "status")
    list_filter = ("status", "leave_type")


@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    list_display = ("date", "name", "kind")
    list_filter = ("kind",)


admin.site.register(ProjectAssignment)
admin.site.register(ProjectUpdate)
admin.site.register(Notification)

from django.urls import include, path
from rest_framework.authtoken.views import obtain_auth_token
from rest_framework.routers import DefaultRouter

from . import api

router = DefaultRouter()
router.register("employees", api.EmployeeViewSet, basename="api-employee")
router.register("departments", api.DepartmentViewSet, basename="api-department")
router.register("teams", api.TeamViewSet, basename="api-team")
router.register("projects", api.ProjectViewSet, basename="api-project")
router.register("leave", api.LeaveViewSet, basename="api-leave")

urlpatterns = [
    path("auth/login/", obtain_auth_token, name="api-login"),
    path("me/", api.me, name="api-me"),
    path("dashboard/", api.dashboard, name="api-dashboard"),
    path("attendance/clock-in/", api.clock_in, name="api-clock-in"),
    path("attendance/clock-out/", api.clock_out, name="api-clock-out"),
    path("attendance/me/", api.my_attendance, name="api-my-attendance"),
    path("attendance/today/", api.attendance_today, name="api-attendance-today"),
    path("leave-balance/", api.leave_balance, name="api-leave-balance"),
    path("holidays/", api.holidays, name="api-holidays"),
    path("", include(router.urls)),
]

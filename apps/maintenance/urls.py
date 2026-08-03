from django.urls import path

from . import views

urlpatterns = [
    path("complaints/new/", views.complaint_new, name="complaint_new"),
    path("complaints/mine/", views.my_complaints, name="my_complaints"),
    path("queue/", views.complaint_queue, name="complaint_queue"),
    path("queue/rows/", views.complaint_queue_rows, name="complaint_queue_rows"),
    path("complaints/<int:pk>/close/", views.complaint_close, name="complaint_close"),
    path(
        "complaints/<int:pk>/confirm/",
        views.complaint_confirm,
        name="complaint_confirm",
    ),
    path(
        "workorders/open/<int:equipment_pk>/",
        views.workorder_open,
        name="workorder_open",
    ),
    path("workorders/<int:pk>/", views.workorder_detail, name="workorder_detail"),
    path("workorders/<int:pk>/start/", views.workorder_start, name="workorder_start"),
    path(
        "workorders/<int:pk>/complete/",
        views.workorder_complete,
        name="workorder_complete",
    ),
    path(
        "workorders/<int:pk>/cancel/", views.workorder_cancel, name="workorder_cancel"
    ),
    path(
        "workorders/<int:pk>/remark/", views.workorder_remark, name="workorder_remark"
    ),
    path("workorders/<int:pk>/join/", views.workorder_join, name="workorder_join"),
    path(
        "ppm/schedule/<int:equipment_pk>/",
        views.ppm_schedule_edit,
        name="ppm_schedule_edit",
    ),
]

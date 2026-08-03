from django.urls import path

from . import views

urlpatterns = [
    path("", views.EquipmentListView.as_view(), name="equipment_list"),
    path("search/", views.EquipmentSearchView.as_view(), name="equipment_search"),
    path("new/", views.EquipmentCreateView.as_view(), name="equipment_create"),
    path("<int:pk>/", views.EquipmentDetailView.as_view(), name="equipment_detail"),
    path("<int:pk>/edit/", views.EquipmentEditView.as_view(), name="equipment_edit"),
    path(
        "<int:pk>/condemn/",
        views.EquipmentCondemnView.as_view(),
        name="equipment_condemn",
    ),
    path("import/", views.EquipmentImportView.as_view(), name="equipment_import"),
    path(
        "import/confirm/",
        views.EquipmentImportConfirmView.as_view(),
        name="equipment_import_confirm",
    ),
    path(
        "accessories/",
        views.AccessoryTypeListView.as_view(),
        name="accessory_type_list",
    ),
    path(
        "accessories/types/new/",
        views.AccessoryTypeCreateView.as_view(),
        name="accessory_type_create",
    ),
    path(
        "accessories/types/<int:pk>/edit/",
        views.AccessoryTypeEditView.as_view(),
        name="accessory_type_edit",
    ),
    path(
        "accessories/types/<int:pk>/stock/",
        views.AccessoryStockAdjustView.as_view(),
        name="accessory_stock_adjust",
    ),
    path(
        "<int:pk>/accessories/attach/",
        views.AccessoryAttachView.as_view(),
        name="accessory_attach",
    ),
    path(
        "accessories/<int:pk>/edit/",
        views.AccessoryEditView.as_view(),
        name="accessory_edit",
    ),
    path(
        "accessories/<int:pk>/condemn/",
        views.AccessoryCondemnView.as_view(),
        name="accessory_condemn",
    ),
    path(
        "accessories/<int:pk>/mark-faulty/<int:wo_pk>/",
        views.AccessoryMarkFaultyView.as_view(),
        name="accessory_mark_faulty",
    ),
    path(
        "accessories/<int:pk>/repair/<int:wo_pk>/",
        views.AccessoryRepairView.as_view(),
        name="accessory_repair",
    ),
    path(
        "accessories/<int:pk>/replace/<int:wo_pk>/",
        views.AccessoryReplaceView.as_view(),
        name="accessory_replace",
    ),
]

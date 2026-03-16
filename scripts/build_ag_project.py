import os
from qgis.PyQt.QtGui import QColor, QFont, QPainter
from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsFillSymbol,
    QgsLineSymbol,
    QgsProject,
    QgsReferencedRectangle,
    QgsRasterLayer,
    QgsRasterShader,
    QgsColorRampShader,
    QgsSingleBandPseudoColorRenderer,
    QgsRasterBandStats,
    QgsSingleSymbolRenderer,
    QgsVectorLayer,
    QgsTextFormat,
    QgsTextBufferSettings,
    QgsPalLayerSettings,
    QgsVectorLayerSimpleLabeling,
)


def create_project():
    base_dir = r"C:\Users\PaulMarzocchi\Vivarium\WinTAK\QGIS-Munster"
    gpkg_path = os.path.join(base_dir, "ag_school_parcels.gpkg")
    project_path = os.path.join(base_dir, "Ag_School_AgParcels.qgz")

    QgsApplication.setPrefixPath(r"C:\OSGeo4W\apps\qgis", True)
    app = QgsApplication([], False)
    app.initQgis()

    try:
        project = QgsProject.instance()
        project.clear()
        project.setFileName(project_path)
        project.setTitle("Agricultural Parcels by School District")
        project.setCrs(QgsCoordinateReferenceSystem("EPSG:26918"))

        def add_vector(
            layer_name: str,
            alias: str,
            symbol_type: str,
            symbol_kwargs: dict,
        ) -> QgsVectorLayer:
            uri = f"{gpkg_path}|layername={layer_name}"
            layer = QgsVectorLayer(uri, alias, "ogr")
            if not layer.isValid():
                raise RuntimeError(f"Failed to load vector layer: {alias}")
            if symbol_type == "polygon":
                symbol = QgsFillSymbol.createSimple(symbol_kwargs)
            elif symbol_type == "line":
                symbol = QgsLineSymbol.createSimple(symbol_kwargs)
            else:
                raise ValueError(f"Unsupported symbol type '{symbol_type}' for {alias}")
            layer.setRenderer(QgsSingleSymbolRenderer(symbol))
            project.addMapLayer(layer, False)
            return layer

        def configure_road_labels(layer: QgsVectorLayer) -> None:
            if "FULLNAME" not in [field.name() for field in layer.fields()]:
                return
            text_format = QgsTextFormat()
            text_format.setFont(QFont("Roboto", 9))
            text_format.setSize(9)
            text_format.setColor(QColor(250, 250, 250))
            buffer = QgsTextBufferSettings()
            buffer.setEnabled(True)
            buffer.setSize(1.2)
            buffer.setColor(QColor(35, 35, 35))
            text_format.setBuffer(buffer)

            settings = QgsPalLayerSettings()
            settings.fieldName = "\"FULLNAME\""
            settings.enabled = True
            settings.isExpression = False
            settings.placement = QgsPalLayerSettings.Curved
            settings.setFormat(text_format)

            labeling = QgsVectorLayerSimpleLabeling(settings)
            layer.setLabeling(labeling)
            layer.setLabelsEnabled(True)
            layer.setMinimumScale(2000000)
            layer.setMaximumScale(0)

        def add_raster(path: str, alias: str) -> QgsRasterLayer:
            layer = QgsRasterLayer(path, alias)
            if not layer.isValid():
                raise RuntimeError(f"Failed to load raster layer: {alias}")
            project.addMapLayer(layer, False)
            return layer

        def add_dem(path: str, alias: str) -> QgsRasterLayer:
            layer = add_raster(path, alias)
            provider = layer.dataProvider()
            stats = provider.bandStatistics(
                1, QgsRasterBandStats.Min | QgsRasterBandStats.Max | QgsRasterBandStats.Mean
            )
            shader = QgsRasterShader()
            color_ramp = QgsColorRampShader()
            color_ramp.setColorRampType(QgsColorRampShader.Interpolated)
            min_val = stats.minimumValue if stats.minimumValue is not None else 0.0
            max_val = stats.maximumValue if stats.maximumValue is not None else min_val + 1.0
            if max_val <= min_val:
                max_val = min_val + 1.0
            mid_val = (min_val + max_val) / 2.0
            color_items = [
                QgsColorRampShader.ColorRampItem(min_val, QColor(34, 94, 168), "Low"),
                QgsColorRampShader.ColorRampItem(mid_val, QColor(144, 238, 144), "Mid"),
                QgsColorRampShader.ColorRampItem(max_val, QColor(205, 133, 63), "High"),
            ]
            color_ramp.setColorRampItemList(color_items)
            shader.setRasterShaderFunction(color_ramp)
            renderer = QgsSingleBandPseudoColorRenderer(provider, 1, shader)
            layer.setRenderer(renderer)
            layer.setOpacity(0.65)
            layer.setBlendMode(QPainter.CompositionMode_SoftLight)
            return layer

        water_area = add_vector(
            "Water_Area",
            "Surface Water",
            "polygon",
            {"color": "70,122,180,160", "outline_color": "70,122,180,60", "outline_width": "0"},
        )

        water_lines = add_vector(
            "Water_Lines",
            "Hydrography (Flowline)",
            "line",
            {"line_color": "70,122,180,255", "line_width": "0.4"},
        )

        roads = add_vector(
            "Roads_Primary",
            "Primary / Secondary Roads",
            "line",
            {"line_color": "230,137,0,255", "line_width": "0.6"},
        )
        configure_road_labels(roads)

        protected = add_vector(
            "Protected_Lands",
            "State & Federal Conservation Lands",
            "polygon",
            {"color": "34,139,34,90", "outline_color": "34,139,34,150", "outline_width": "0.3"},
        )

        wildlife_units = add_vector(
            "Wildlife_Management_Units",
            "Wildlife Management Units",
            "polygon",
            {"color": "128,0,128,45", "outline_color": "128,0,128,150", "outline_width": "0.6"},
        )

        ag_districts = add_vector(
            "Ag_Districts_Focus",
            "Ag District Footprints",
            "polygon",
            {"color": "65,105,225,70", "outline_color": "65,105,225,180", "outline_width": "0.3"},
        )

        candidate = add_vector(
            "Candidate_Parcels",
            "School District Parcels",
            "polygon",
            {"color": "0,0,0,0", "outline_color": "80,80,80,160", "outline_width": "0.15"},
        )

        ag_zoned = add_vector(
            "Ag_Zoned_Parcels",
            "Ag Zoned Parcels",
            "polygon",
            {"color": "0,156,90,180", "outline_color": "255,255,255,120", "outline_width": "0.3"},
        )

        school = add_vector(
            "School_Districts_Target",
            "Target School District Boundaries",
            "polygon",
            {"color": "0,0,0,0", "outline_color": "255,215,0,255", "outline_width": "0.9"},
        )

        hunt_line = add_vector(
            "Hunting_NorthSouth_Line",
            "Northern / Southern Hunting Zone Line",
            "line",
            {"line_color": "255,0,0,255", "line_width": "0.8", "line_style": "dash"},
        )

        onondaga_dem = add_dem(
            os.path.join(base_dir, "Elevation", "onondaga_dem_clipped.tif"),
            "Onondaga Elevation (DEM)",
        )
        stlawrence_dem = add_dem(
            os.path.join(base_dir, "Elevation", "stlawrence_dem_clipped.tif"),
            "St. Lawrence Elevation (DEM)",
        )

        onondaga_hillshade = add_raster(
            os.path.join(base_dir, "Elevation", "onondaga_hillshade.tif"),
            "Onondaga Hillshade",
        )
        stlawrence_hillshade = add_raster(
            os.path.join(base_dir, "Elevation", "stlawrence_hillshade.tif"),
            "St. Lawrence Hillshade",
        )
        for hs_layer in (onondaga_hillshade, stlawrence_hillshade):
            hs_layer.setOpacity(0.4)
            hs_layer.setBlendMode(QPainter.CompositionMode_Multiply)

        sat_source = (
            "type=xyz&zmin=0&zmax=19&url="
            "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
        )
        imagery = QgsRasterLayer(sat_source, "ESRI World Imagery", "wms")
        if not imagery.isValid():
            raise RuntimeError("Failed to load ESRI World Imagery basemap")
        project.addMapLayer(imagery, False)

        root = project.layerTreeRoot()
        for lyr in (
            imagery,
            onondaga_hillshade,
            stlawrence_hillshade,
            onondaga_dem,
            stlawrence_dem,
            water_area,
            water_lines,
            roads,
            protected,
            wildlife_units,
            ag_districts,
            candidate,
            ag_zoned,
            school,
            hunt_line,
        ):
            root.addLayer(lyr)

        extent = ag_zoned.extent() if ag_zoned.featureCount() else candidate.extent()
        if not extent.isEmpty():
            buffer_ratio = 0.05
            dx = extent.width() * buffer_ratio
            dy = extent.height() * buffer_ratio
            extent.setXMinimum(extent.xMinimum() - dx)
            extent.setXMaximum(extent.xMaximum() + dx)
            extent.setYMinimum(extent.yMinimum() - dy)
            extent.setYMaximum(extent.yMaximum() + dy)
            referenced = QgsReferencedRectangle(extent, QgsCoordinateReferenceSystem("EPSG:26918"))
            project.viewSettings().setDefaultViewExtent(referenced)

        if not project.write():
            raise RuntimeError("Failed to save project file")

        print(f"Project written to: {project_path}")
    finally:
        app.exitQgis()


if __name__ == "__main__":
    create_project()

import { useEffect, useState } from 'react'
import { Circle, CircleMarker, ImageOverlay, MapContainer, Polygon, TileLayer, Tooltip, useMap, useMapEvents } from 'react-leaflet'
import { level } from '../lib/levels'
import { useT } from '../lib/i18n'

// Peninsular Malaysia (spec FR-01)
const BOUNDS = [
  [1.2, 99.6],
  [6.8, 104.5],
]
const MAX_BOUNDS = [
  [-0.5, 97.5],
  [8.5, 106.5],
]
const RADAR_OPACITY = 0.7
// Below this zoom a 2.5 km circle is a few pixels wide; draw a fixed-size marker instead (affordance).
const MARKER_BELOW_ZOOM = 9
// OpenStreetMap tiles, shown in greyscale (index.css) for a calm base. CARTO basemaps now need an API key.
const BASEMAP = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'

function FlyTo({ zone }) {
  const map = useMap()
  useEffect(() => {
    if (zone) map.flyTo([zone.lat, zone.lon], Math.max(map.getZoom(), 10), { duration: 0.6 })
  }, [zone, map])
  return null
}

function ClickToSet({ onPick }) {
  useMapEvents({ click: (e) => onPick?.({ lat: +e.latlng.lat.toFixed(4), lon: +e.latlng.lng.toFixed(4) }) })
  return null
}

function useZoom() {
  const map = useMap()
  const [zoom, setZoom] = useState(map.getZoom())
  useMapEvents({ zoomend: () => setZoom(map.getZoom()) })
  return zoom
}

function ZoneShape({ zone, selected, onSelect, zoom }) {
  const { t } = useT()
  const l = level(zone.level)
  const style = {
    color: selected ? '#18302E' : l.color,
    weight: selected ? 4 : 2,
    fillColor: l.color,
    fillOpacity: 0.38,
    className: 'zone-shape',
  }
  const handlers = { click: () => onSelect?.(zone) }
  const tooltip = (
    <Tooltip direction="top" offset={[0, -6]}>
      <strong>{zone.name}</strong> · {t(`level.${l.key}`)}
    </Tooltip>
  )
  const coords = zone.polygon?.type === 'Polygon' ? zone.polygon.coordinates[0].map(([lon, lat]) => [lat, lon]) : null
  return (
    <>
      {zone.level === 'RED' && zoom >= MARKER_BELOW_ZOOM && (
        <Circle center={[zone.lat, zone.lon]} radius={zone.radius_m || 2500} interactive={false} pathOptions={{ color: l.color, fill: false, weight: 2, className: 'zone-pulse' }} />
      )}
      {zoom < MARKER_BELOW_ZOOM ? (
        <CircleMarker center={[zone.lat, zone.lon]} radius={selected ? 10 : 8} pathOptions={{ ...style, fillOpacity: 0.9, weight: 2, color: selected ? '#18302E' : '#FFFFFF' }} eventHandlers={handlers}>
          {tooltip}
        </CircleMarker>
      ) : coords ? (
        <Polygon positions={coords} pathOptions={style} eventHandlers={handlers}>
          {tooltip}
        </Polygon>
      ) : (
        <Circle center={[zone.lat, zone.lon]} radius={zone.radius_m || 2500} pathOptions={style} eventHandlers={handlers}>
          {tooltip}
        </Circle>
      )}
    </>
  )
}

function Zones({ zones, selectedId, onSelect }) {
  const zoom = useZoom()
  // Selected and RED zones draw last so they sit on top of neighbours.
  const ordered = [...zones].sort((a, b) => (a.id === selectedId) - (b.id === selectedId) || level(a.level).rank - level(b.level).rank)
  return ordered.map((z) => <ZoneShape key={z.id} zone={z} selected={z.id === selectedId} onSelect={onSelect} zoom={zoom} />)
}

/**
 * frames: [{ ts, kind: 'observed' | 'nowcast', tile_url?, image_url?, bounds? }]
 * All radar layers stay mounted and only the active one is visible, so playback doesn't flicker.
 */
export default function RadarMap({ zones = [], frames = [], activeIndex = -1, selectedId, onSelect, onPick, focusZone, className = '' }) {
  return (
    <MapContainer
      bounds={BOUNDS}
      maxBounds={MAX_BOUNDS}
      minZoom={6}
      maxZoom={12}
      zoomSnap={0.5}
      className={`h-full w-full ${className}`}
      attributionControl={false}
    >
      <TileLayer url={BASEMAP} className="basemap" maxZoom={19} />
      {frames.map((f, i) =>
        f.kind === 'observed' && f.tile_url ? (
          <TileLayer key={f.ts} url={f.tile_url} opacity={i === activeIndex ? RADAR_OPACITY : 0} maxNativeZoom={7} maxZoom={12} zIndex={10} />
        ) : f.image_url ? (
          <ImageOverlay key={f.ts} url={f.image_url} bounds={f.bounds} opacity={i === activeIndex ? RADAR_OPACITY : 0} zIndex={10} />
        ) : null,
      )}
      <Zones zones={zones} selectedId={selectedId} onSelect={onSelect} />
      <FlyTo zone={focusZone} />
      {onPick && <ClickToSet onPick={onPick} />}
    </MapContainer>
  )
}

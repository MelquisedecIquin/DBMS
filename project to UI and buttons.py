<!DOCTYPE html>
<html>
<head>
    <title>Risk Mapping System</title>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="https://unpkg.com/leaflet/dist/leaflet.css"/>
    <style>
        body { margin:0; font-family: Arial; display:flex; height:100vh; overflow:hidden; }
        .sidebar { width:300px; background:#1e293b; color:white; padding:20px; box-sizing:border-box; }
        input, button { width:100%; padding:10px; margin-top:10px; border-radius:5px; border:none; }
        button { background:#3b82f6; color:white; cursor:pointer; }
        button:hover { background:#2563eb; }
        .info-box { margin-top:15px; background:#334155; padding:10px; border-radius:5px; font-size:14px; }
        #map { flex:1; height:100vh; }
        .risk-badge { display:inline-block; padding:3px 8px; border-radius:5px; color:white; font-weight:bold; }
        .low { background:#22c55e; } .medium { background:#facc15; color:black; } .high { background:#ef4444; }
    </style>
</head>
<body>
<div class="sidebar">
    <h2>🌍Earthquake Map</h2>
    <input id="lat" placeholder="Latitude">
    <input id="lng" placeholder="Longitude">
    <button onclick="updateMap()">Show Coordinates / Assessment</button>
    <div class="info-box" id="info">Loading earthquake data...</div>
</div>
<div id="map"></div>

<script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>
<script>
let map = L.map('map').setView([14.5995, 120.9842], 6);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution:'© OpenStreetMap' }).addTo(map);

let marker, earthquakeData=[], faultData=[], dataLoaded=false;

fetch("phivolcs_earthquake_data.csv").then(r=>r.text()).then(txt=>{
    earthquakeData = txt.split("\n").slice(1).map(row=>{
        let [lat,lng,mag,depth,date] = row.split(",");
        return {lat:+lat,lng:+lng,magnitude:+mag,depth,date};
    }).filter(e=>!isNaN(e.lat));
    dataLoaded = true;
    document.getElementById("info").innerText="Click the map or enter coordinates.";
});

fetch("philippines_faults.geojson").then(r=>r.json()).then(data=>{
    faultData = data;
    L.geoJSON(data,{style:{color:"red",weight:2}}).addTo(map);
});

function nearestEarthquake(lat,lng){
    if(!earthquakeData.length) return null;
    let eq = earthquakeData.reduce((p,c)=> Math.hypot(c.lat-lat,c.lng-lng)<Math.hypot(p.lat-lat,p.lng-lng)?c:p );
    return Math.hypot(eq.lat-lat,eq.lng-lng)<=0.5 ? eq : null; // ~50km threshold
}

function nearestFault(lat,lng){
    if(!faultData) return "Unknown";
    let nearest=null,min=Infinity;
    faultData.features.forEach(f=>{
        f.geometry.coordinates.flat(2).forEach((v,i,a)=>{
            if(i%2===0) return; // skip lng
            let dist=Math.hypot(a[i]-lat,a[i-1]-lng);
            if(dist<min){min=dist; nearest=f.properties.name;}
        });
    });
    return nearest||"Unknown";
}

function riskAssessment(mag){
    if(mag<4) return {level:"Low",class:"low",damage:"Minor/no damage"};
    if(mag<6) return {level:"Medium",class:"medium",damage:"Moderate damage possible"};
    return {level:"High",class:"high",damage:"Severe damage likely"};
}

//pang update ng map info to
function updateMap(){
    let lat=+document.getElementById("lat").value;
    let lng=+document.getElementById("lng").value;
    if(isNaN(lat)||isNaN(lng)){ alert("Enter valid coordinates"); return; }
    map.setView([lat,lng],10);
    if(marker) map.removeLayer(marker); marker=L.marker([lat,lng]).addTo(map);

    if(!dataLoaded){ alert("Data still loading"); return; }

    let eq=nearestEarthquake(lat,lng);
    if(!eq){ document.getElementById("info").innerText="No nearby earthquake data."; return; }

    let fault=nearestFault(lat,lng), assessment=riskAssessment(eq.magnitude);
    document.getElementById("info").innerHTML=
        `<b>Lat:</b> ${lat.toFixed(5)}<br>
         <b>Lng:</b> ${lng.toFixed(5)}<br>
         <b>Magnitude:</b> ${eq.magnitude}<br>
         <b>Depth:</b> ${eq.depth}<br>
         <b>Date:</b> ${eq.date}<br>
         <b>Fault:</b> ${fault}<br>
         <b>Risk:</b> <span class="risk-badge ${assessment.class}">${assessment.level}</span><br>
         <b>Damage:</b> ${assessment.damage}`;
    marker.bindPopup(`Magnitude:${eq.magnitude}<br>Date:${eq.date}<br>Depth:${eq.depth}<br>Fault:${fault}<br>Risk:${assessment.level}<br>Damage:${assessment.damage}`).openPopup();
}

//map clicking feature
map.on('click', e=>{
    document.getElementById("lat").value=e.latlng.lat.toFixed(5);
    document.getElementById("lng").value=e.latlng.lng.toFixed(5);
    updateMap();
});
</script>
</body>
</html>

import re
import requests
import logging
import plotly.graph_objects as go
from bs4 import BeautifulSoup
from pymongo import MongoClient
from datetime import datetime, timedelta
from collections import Counter
import pandas as pd
import streamlit as st

# 🐝 Pripojenie k MongoDB
MONGO_URL = "mongodb+srv://halasfilip5:Benkovce%402231@cluster0.4igee.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
client = MongoClient(MONGO_URL)
db = client["novinove_clanky"]

# 📌 Kolekcie v MongoDB
filter_keywords_collection = db["filter_keywords"]
collection = db["analyza_slov_2"]

# 🔄 Zistenie prvého a posledného dátumu
def get_date_range():
    default_start = "2025-03-01"
    default_end = datetime.now().strftime("%Y-%m-%d")
    
    first_article = collection.find_one({}, sort=[("Datum_publikacie", 1)])
    latest_article = collection.find_one({}, sort=[("Datum_publikacie", -1)])
    
    first_date = first_article["Datum_publikacie"] if first_article and first_article["Datum_publikacie"] else default_start
    last_date = latest_article["Datum_publikacie"] if latest_article and latest_article["Datum_publikacie"] else default_end
    
    return first_date, last_date

first_date, last_date = get_date_range()

# 🔍 Načítanie sekcií
categories = list(filter_keywords_collection.distinct("category")) + ["iné"]

def get_articles_by_category(category, start_date=None, end_date=None):
    query = {}

    if category == "iné":
        query["Sekcia"] = {"$nin": ["politika", "ekonomika", "vojna", "zahraničie"]}  
    else:
        query["Sekcia"] = category

    start_date_str = start_date.strftime("%Y-%m-%d")
    end_date_str = end_date.strftime("%Y-%m-%d")

    query["$and"] = [
        {"Datum_publikacie": {"$gte": start_date_str, "$lte": end_date_str}},
        {"URL": {"$regex": "aktuality|dennikn|pravda"}}
    ]

    articles = list(collection.find(query, {"_id": 0, "URL": 1, "Datum_publikacie": 1, "Najcastejsie_slovo": 1, "Pocet": 1, "Sekcia": 1}))
    articles = [article for article in articles if "URL" in article and "Datum_publikacie" in article]
    sorted_articles = sorted(articles, key=lambda x: (x["Datum_publikacie"], x["URL"].split("/")[2]), reverse=True)
    return sorted_articles

# 🔍 Funkcia pre sledovanie vývoja top slov
def get_top_word_trends(start_date, end_date, category=None, limit=5, aggregation="day"):
    match_query = {
        "Datum_publikacie": {
            "$gte": start_date.strftime("%Y-%m-%d"),
            "$lte": end_date.strftime("%Y-%m-%d")
        },
        "URL": {"$regex": "aktuality|dennikn|pravda"}
    }

    if category:
        if category == "iné":
            match_query["Sekcia"] = {"$nin": ["politika", "ekonomika", "vojna", "zahraničie"]}
        else:
            match_query["Sekcia"] = category

    pipeline = [
        {"$match": match_query},
        {"$group": {"_id": "$Najcastejsie_slovo", "count": {"$sum": "$Pocet"}}},
        {"$sort": {"count": -1}},
        {"$limit": limit}
    ]
    top_words = [word["_id"] for word in collection.aggregate(pipeline)]

    date_grouping = "$Datum_publikacie" if aggregation == "day" else {
        "$dateTrunc": {"date": "$Datum_publikacie", "unit": "week"}
    }

    trends_pipeline = [
        {"$match": match_query},
        {"$addFields": {"Datum_publikacie": {"$toDate": "$Datum_publikacie"}}},
        {"$group": {
            "_id": {"word": "$Najcastejsie_slovo", "date": date_grouping},
            "count": {"$sum": "$Pocet"}
        }},
        {"$sort": {"_id.date": 1}}
    ]

    results = list(collection.aggregate(trends_pipeline))
    trends = {}
    for entry in results:
        word = entry["_id"]["word"]
        date = entry["_id"]["date"]
        count = entry["count"]
        if word in top_words:
            if word not in trends:
                trends[word] = []
            trends[word].append((date, count))

    return trends 

# 📰 Streamlit UI
st.title("\U0001F4F0 Analýza Novinových Článkov")
selected_category = st.selectbox("Vyberte sekciu:", categories)

top_n = st.selectbox("Vyberte počet najčastejších slov:", [5, 10], index=0)
view_type = st.radio("Vyberte typ grafu:", ["Histogram", "Finančný graf"], index=0)
time_aggregation = st.radio("Vyberte časové rozlíšenie:", ["Denné", "Týždenné"], index=0)

start_date = st.date_input("Od dátumu", datetime.strptime(first_date, "%Y-%m-%d"))
end_date = st.date_input("Do dátumu", datetime.strptime(last_date, "%Y-%m-%d"))

display_option = st.radio("Vyberte, čo chcete zobraziť:", ["Zobraziť vývoj slov", "Zobraziť články"])

if display_option == "Zobraziť vývoj slov":
    if st.button("Zobraziť vývoj slov"):
        aggregation_type = "day" if time_aggregation == "Denné" else "week"
        trends = get_top_word_trends(start_date, end_date, selected_category, top_n, aggregation_type)
        if trends:
            fig = go.Figure()
            if view_type == "Histogram":
                for word, values in trends.items():
                    values.sort()
                    dates, counts = zip(*values)
                    fig.add_trace(go.Bar(x=dates, y=counts, name=word))
            else:
                for word, values in trends.items():
                    values.sort()
                    dates, counts = zip(*values)
                    fig.add_trace(go.Scatter(x=dates, y=counts, mode="lines+markers", name=word, line_shape='linear', marker=dict(size=8)))

            fig.update_layout(
                title=f"📊 Vývoj top {top_n} slov v sekcii '{selected_category}' ({time_aggregation})",
                xaxis_title=f"Dátum ({time_aggregation} údaje)",
                yaxis_title="Počet výskytov",
                xaxis=dict(
                    type="date",
                    tickformat="%d. %b %Y"
                ),
                height=700,
                width=1200,
                legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
                yaxis=dict(showgrid=True, zeroline=True, showline=True, showticklabels=True, rangemode="tozero"),
            )
            st.plotly_chart(fig)
        else:
            st.warning("❌ Žiadne dáta pre graf.")

elif display_option == "Zobraziť články":
    if st.button("Zobraziť články"):
        articles = get_articles_by_category(selected_category, start_date, end_date)
        if articles:
            st.subheader(f"📰 Články v sekcii '{selected_category}' od {start_date} do {end_date}")
            for article in articles:
                st.write(f"**{article['Datum_publikacie']}** - {article['URL']} - Najčastejšie slovo: {article['Najcastejsie_slovo']} (Počet: {article['Pocet']})")
        else:
            st.warning("❌ Žiadne články pre túto sekciu v zadanom období.")



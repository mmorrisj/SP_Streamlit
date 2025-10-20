from flask import Flask, send_from_directory, render_template
from backend.scripts.models import Document, Category, Subcategory, InitiatingCountry, RecipientCountry, Project, Event
from backend.extensions import db
import os
from dotenv import load_dotenv

load_dotenv()
def register_routes(app):

    @app.route('/')
    def index():
        return render_template("index.html")

    @app.route('/api/documents', methods=['GET'])
    def get_documents():
        documents = Document.query.all()
        return {"documents": [doc.to_dict() for doc in documents]}

    @app.route('/api/documents/<int:doc_id>', methods=['GET'])
    def get_document(doc_id):
        document = Document.query.get_or_404(doc_id)
        return document.to_dict()

    @app.route('/api/documents/<int:doc_id>/categories', methods=['GET'])
    def get_document_categories(doc_id):
        categories = Category.query.filter_by(atom_id=doc_id).all()
        return {"categories": [cat.to_dict() for cat in categories]}

    @app.route('/api/documents/<int:doc_id>/subcategories', methods=['GET'])
    def get_document_subcategories(doc_id):
        subcategories = Subcategory.query.filter_by(atom_id=doc_id).all()
        return {"subcategories": [subcat.to_dict() for subcat in subcategories]}

    @app.route('/api/documents/<int:doc_id>/initiating_countries', methods=['GET'])
    def get_document_initiating_countries(doc_id):
        initiating_countries = InitiatingCountry.query.filter_by(atom_id=doc_id).all()
        return {"initiating_countries": [country.to_dict() for country in initiating_countries]}
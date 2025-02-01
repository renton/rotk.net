
class DbManager:
    def __init__(self, db):
        self.db = db

    def print_records(self, model):
        pass

    def get_col_names(self, model):
        return [c_attr.key for c_attr in inspect(model).mapper.column_attrs]

    def add_row(self, model, data):
        row = model(**data)
        try:            
            self.db.session.add(row)
            self.db.session.commit()
            return row
        except Exception as e:          
            print("!!!!!!", (e.args))
            self.db.session.rollback()
            return None

    def update_row(self, model, instance, data):
        for k,v in data.items():
            setattr(instance, k, v)
        try:
            self.db.session.commit()
            return instance
        except Exception as e:
            print(e)
            db.session.rollback()
            return None

    def delete_all(self, model):
        try:
            self.db.session.query(model).delete()
            self.db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Error deleting records: {str(e)}")
